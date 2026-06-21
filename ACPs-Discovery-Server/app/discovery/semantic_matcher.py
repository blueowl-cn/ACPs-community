import numpy as np
from typing import List, Dict, Any, Tuple, Optional, Set
import json
import pickle
import os
from datetime import datetime
import logging
from sklearn.metrics.pairwise import cosine_similarity
import jieba
import re
from pathlib import Path
from app.core.config import settings
from openai import AsyncOpenAI
logger = logging.getLogger(__name__)


class SemanticAgentMatcher:
    """基于语义相似度的智能体匹配器"""
    
    def __init__(self, 
                api_key: str = None,
                api_endpoint: str = None,
                model_name: str = "text-embedding-3-small",  # 或其他支持的embedding模型
                cache_dir: str = 'semantic_cache',
                similarity_threshold: float = 0.3):
        """
        初始化语义匹配器
        
        Args:
            api_key: OPENAI API密钥
            api_endpoint: OPENAI API端点
            model_name: Embedding模型名称
            cache_dir: 缓存目录
            similarity_threshold: 相似度阈值
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.api_endpoint = api_endpoint or settings.OPENAI_BASE_URL
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        if not self.api_key:
            raise ValueError("未找到API密钥，请在配置中设置 OPENAI_API_KEY")

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_endpoint
        )        
        script_path = Path(__file__).resolve()
        script_dir = script_path.parent
        self.cache_dir = (script_dir / cache_dir).resolve()
        self.cache_dir.mkdir(exist_ok=True, parents=True)
        self.similarity_threshold = similarity_threshold
        
        # 智能体embedding缓存
        self.agent_embeddings = {}
        self.agent_keywords = {}
        self.agent_summaries = {}
        
        # 缓存文件路径
        self.embeddings_cache_file = os.path.join(cache_dir, 'agent_embeddings.pkl')
        self.keywords_cache_file = os.path.join(cache_dir, 'agent_keywords.pkl')
        self.summaries_cache_file = os.path.join(cache_dir, 'agent_summaries.pkl')
        
        # 加载缓存
        self._load_cache()
        
        # 配置权重保持不变
        self.semantic_config = {
            "skill_weight": 0.4,
            "description_weight": 0.3,
            "tags_weight": 0.2,
            "name_weight": 0.1,
            "min_similarity": 0.1,
            "boost_exact_match": 1.5,
        }
    

    async def _get_embedding_from_api(self, text: str) -> np.ndarray:
        """
        调用大模型API生成embedding
        
        Args:
            text: 需要生成embedding的文本
            
        Returns:
            embedding向量(numpy数组)
        """
        try:
            response = await self.client.embeddings.create(
                model=self.model_name,
                input=text
            )
            
            # 从响应中提取 embedding
            embedding = response.data[0].embedding
            return np.array(embedding)
            
        except Exception as e:
            logger.error(f"生成embedding失败: {e}")
            raise Exception(f"Embedding API错误: {str(e)}")

    async def _get_embeddings_batch(self, texts: List[str]) -> List[np.ndarray]:
        """
        批量生成embeddings（使用 OpenAI SDK）
        
        Args:
            texts: 文本列表
            
        Returns:
            embedding向量列表
        """
        try:
            response = await self.client.embeddings.create(
                model=self.model_name,
                input=texts  # 批量输入
            )
            
            # 从响应中提取所有 embeddings
            embeddings = [np.array(item.embedding) for item in response.data]
            return embeddings
            
        except Exception as e:
            logger.warning(f"批量embedding失败，回退到逐个处理: {e}")
            # 如果批量失败，回退到逐个处理
            embeddings = []
            for text in texts:
                embedding = await self._get_embedding_from_api(text)
                embeddings.append(embedding)
            return embeddings


    def _load_cache(self):
        """从磁盘加载缓存数据"""
        try:
            if os.path.exists(self.embeddings_cache_file):
                with open(self.embeddings_cache_file, 'rb') as f:
                    self.agent_embeddings = pickle.load(f)
                logger.info(f"加载了 {len(self.agent_embeddings)} 个智能体的embedding缓存")
            
            if os.path.exists(self.keywords_cache_file):
                with open(self.keywords_cache_file, 'rb') as f:
                    self.agent_keywords = pickle.load(f)
                logger.info(f"加载了 {len(self.agent_keywords)} 个智能体的关键词缓存")
                
            if os.path.exists(self.summaries_cache_file):
                with open(self.summaries_cache_file, 'rb') as f:
                    self.agent_summaries = pickle.load(f)
                logger.info(f"加载了 {len(self.agent_summaries)} 个智能体的摘要缓存")
                    
        except Exception as e:
            logger.warning(f"加载缓存失败: {e}")
            self.agent_embeddings = {}
            self.agent_keywords = {}
            self.agent_summaries = {}
    
    def _save_cache(self):
        """保存缓存到磁盘"""
        try:
            with open(self.embeddings_cache_file, 'wb') as f:
                pickle.dump(self.agent_embeddings, f)
            
            with open(self.keywords_cache_file, 'wb') as f:
                pickle.dump(self.agent_keywords, f)
                
            with open(self.summaries_cache_file, 'wb') as f:
                pickle.dump(self.agent_summaries, f)
                
            logger.info("缓存保存成功")
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    def _extract_chinese_keywords(self, text: str) -> List[str]:
        """提取中文关键词"""
        if not text:
            return []
        
        # 使用jieba分词
        words = jieba.lcut(text)
        
        # 过滤停用词和短词
        stop_words = {'的', '和', '或', '但是', '因为', '所以', '我', '你', '他', '她', '它', 
                     '我们', '你们', '他们', '这', '那', '这个', '那个', '一个', '可以', '能够',
                     '进行', '实现', '提供', '支持', '使用', '通过', '基于', '具有'}
        
        keywords = []
        for word in words:
            # 过滤停用词、标点符号、纯数字、过短的词
            if (len(word) >= 2 and 
                word not in stop_words and 
                not re.match(r'^[0-9]+$', word) and
                not re.match(r'^[^\w]+$', word)):
                keywords.append(word.lower())
        
        return keywords
    
    def _extract_english_keywords(self, text: str) -> List[str]:
        """提取英文关键词"""
        if not text:
            return []
        
        # 清理文本并分词
        cleaned_text = re.sub(r'[^\w\s]', ' ', text.lower())
        words = cleaned_text.split()
        
        # 英文停用词
        stop_words = {'the', 'and', 'or', 'but', 'because', 'so', 'i', 'you', 'he', 'she', 
                     'it', 'we', 'they', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 
                     'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 
                     'may', 'might', 'can', 'must', 'shall', 'a', 'an', 'this', 'that', 
                     'these', 'those', 'my', 'your', 'his', 'her', 'its', 'our', 'their'}
        
        keywords = []
        for word in words:
            if len(word) >= 3 and word not in stop_words:
                keywords.append(word)
        
        return keywords
    
    def _extract_agent_keywords(self, agent: Dict[str, Any]) -> Dict[str, List[str]]:
        """从智能体信息中提取结构化关键词 - 适配新ACS结构"""
        keywords = {
            'skills': [],
            'tags': [],
            'description': [],
            'name': [],
            'capabilities': []
        }
        
        # 提取技能关键词
        for skill in agent.get('skills', []):
            # 技能名称
            skill_name = skill.get('name', '')
            keywords['skills'].extend(self._extract_chinese_keywords(skill_name))
            keywords['skills'].extend(self._extract_english_keywords(skill_name))
            
            # 技能描述
            skill_desc = skill.get('description', '')
            keywords['capabilities'].extend(self._extract_chinese_keywords(skill_desc))
            keywords['capabilities'].extend(self._extract_english_keywords(skill_desc))
            
            # 技能标签
            skill_tags = skill.get('tags', [])
            for tag in skill_tags:
                keywords['tags'].extend(self._extract_chinese_keywords(tag))
                keywords['tags'].extend(self._extract_english_keywords(tag))
            
            # 新ACS结构：处理inputModes和outputModes
            input_modes = skill.get('inputModes', [])
            output_modes = skill.get('outputModes', [])
            for mode in input_modes + output_modes:
                keywords['capabilities'].extend(self._extract_english_keywords(mode))
        
        # 提取描述关键词
        description = agent.get('description', '')
        keywords['description'].extend(self._extract_chinese_keywords(description))
        keywords['description'].extend(self._extract_english_keywords(description))
        
        # 提取名称关键词
        name = agent.get('name', '')
        keywords['name'].extend(self._extract_chinese_keywords(name))
        keywords['name'].extend(self._extract_english_keywords(name))
        
        # 新ACS结构：处理defaultInputModes和defaultOutputModes
        default_input_modes = agent.get('defaultInputModes', [])
        default_output_modes = agent.get('defaultOutputModes', [])
        for mode in default_input_modes + default_output_modes:
            keywords['capabilities'].extend(self._extract_english_keywords(mode))
        
        # 新ACS结构：处理capabilities字段
        capabilities = agent.get('capabilities', {})
        if isinstance(capabilities, dict):
            for key, value in capabilities.items():
                if isinstance(value, bool) and value:
                    keywords['capabilities'].extend(self._extract_english_keywords(key))
                elif isinstance(value, (str, list)):
                    cap_text = str(value) if isinstance(value, str) else ' '.join(str(v) for v in value)
                    keywords['capabilities'].extend(self._extract_english_keywords(cap_text))
        
        # 去重并过滤
        for key in keywords:
            keywords[key] = list(set([kw for kw in keywords[key] if len(kw) >= 2]))
        
        return keywords
    
    def _create_agent_summary(self, agent: Dict[str, Any]) -> str:
        """创建智能体能力摘要文本，用于生成embedding - 适配新ACS结构"""
        summary_parts = []
        
        # 智能体名称和描述
        name = agent.get('name', '')
        description = agent.get('description', '')
        if name:
            summary_parts.append(f"智能体名称: {name}")
        if description:
            summary_parts.append(f"功能描述: {description}")
        
        # 技能摘要
        skills_summary = []
        for skill in agent.get('skills', []):
            skill_name = skill.get('name', '')
            skill_desc = skill.get('description', '')
            skill_tags = ', '.join(skill.get('tags', []))
            
            skill_text = f"{skill_name}"
            if skill_desc:
                skill_text += f": {skill_desc}"
            if skill_tags:
                skill_text += f" (标签: {skill_tags})"
            
            skills_summary.append(skill_text)
        
        if skills_summary:
            summary_parts.append("主要技能: " + "; ".join(skills_summary))
        
        # 新ACS结构：处理inputModes和outputModes
        input_types = set()
        output_types = set()
        for skill in agent.get('skills', []):
            # 使用新的字段名
            input_types.update(skill.get('inputModes', []))
            output_types.update(skill.get('outputModes', []))
        
        # 也处理智能体级别的默认模式
        input_types.update(agent.get('defaultInputModes', []))
        output_types.update(agent.get('defaultOutputModes', []))
        
        if input_types:
            summary_parts.append(f"支持输入类型: {', '.join(input_types)}")
        if output_types:
            summary_parts.append(f"输出类型: {', '.join(output_types)}")
        
        # 新ACS结构：处理capabilities
        capabilities = agent.get('capabilities', {})
        if isinstance(capabilities, dict):
            cap_features = []
            for key, value in capabilities.items():
                if isinstance(value, bool) and value:
                    cap_features.append(key)
                elif isinstance(value, list) and value:
                    cap_features.append(f"{key}: {', '.join(str(v) for v in value)}")
            if cap_features:
                summary_parts.append(f"技术能力: {'; '.join(cap_features)}")
        
        # 新ACS结构：处理提供商信息
        provider = agent.get('provider', {})
        if isinstance(provider, dict):
            org = provider.get('organization', '')
            dept = provider.get('department', '')
            if org:
                provider_text = org
                if dept:
                    provider_text += f" - {dept}"
                summary_parts.append(f"提供商: {provider_text}")
        
        return "; ".join(summary_parts)
    
    async def build_agent_index(self, agents: List[Dict[str, Any]], force_rebuild: bool = False):
        """
        构建智能体语义索引（使用API生成embedding）
        
        Args:
            agents: 智能体列表
            force_rebuild: 是否强制重建索引
        """
        logger.info(f"开始构建 {len(agents)} 个智能体的语义索引...")
        
        new_agents = 0
        updated_agents = 0
        
        # 收集需要生成embedding的智能体
        agents_to_process = []
        summaries_to_embed = []
        
        for agent in agents:
            agent_aic = agent.get('aic', agent.get('AIC', ''))
            if not agent_aic:
                continue
            
            # 检查是否需要更新
            agent_mod_time = agent.get('lastModifiedTime', '')
            cached_time = self.agent_summaries.get(agent_aic, {}).get('mod_time', '')
            
            if not force_rebuild and agent_aic in self.agent_embeddings and agent_mod_time == cached_time:
                continue
            
            try:
                # 提取关键词
                keywords = self._extract_agent_keywords(agent)
                
                # 创建摘要
                summary = self._create_agent_summary(agent)
                
                agents_to_process.append({
                    'aic': agent_aic,
                    'keywords': keywords,
                    'summary': summary,
                    'mod_time': agent_mod_time
                })
                summaries_to_embed.append(summary)
                
            except Exception as e:
                logger.error(f"处理智能体 {agent_aic} 失败: {e}")
        
        # 批量生成embeddings
        if summaries_to_embed:
            logger.info(f"正在为 {len(summaries_to_embed)} 个智能体生成embeddings...")
            try:
                embeddings = await self._get_embeddings_batch(summaries_to_embed)
                
                # 存储结果
                for agent_info, embedding in zip(agents_to_process, embeddings):
                    agent_aic = agent_info['aic']
                    
                    self.agent_keywords[agent_aic] = agent_info['keywords']
                    self.agent_summaries[agent_aic] = {
                        'summary': agent_info['summary'],
                        'mod_time': agent_info['mod_time'],
                        'build_time': datetime.now().isoformat()
                    }
                    self.agent_embeddings[agent_aic] = embedding
                    
                    if agent_aic in self.agent_embeddings:
                        updated_agents += 1
                    else:
                        new_agents += 1
                        
            except Exception as e:
                logger.error(f"批量生成embeddings失败: {e}")
        
        # 保存缓存
        self._save_cache()
        
        logger.info(f"语义索引构建完成: 新增 {new_agents} 个，更新 {updated_agents} 个")

    async def _update_agent_index(self, agent_data: Dict[str, Any]):
        """更新单个智能体的语义索引 - 使用API生成embedding"""
        # 新ACS结构使用'aic'而不是'AIC'
        agent_aic = agent_data.get('aic', agent_data.get('AIC', ''))
        if not agent_aic:
            return
        
        # 检查是否需要更新
        agent_mod_time = agent_data.get('lastModifiedTime', '')
        cached_time = self.agent_summaries.get(agent_aic, {}).get('mod_time', '')
        
        # 如果智能体已存在且未修改，则跳过
        if agent_aic in self.agent_embeddings and agent_mod_time == cached_time:
            return
        
        try:
            # 提取关键词
            keywords = self._extract_agent_keywords(agent_data)
            
            # 创建摘要
            summary = self._create_agent_summary(agent_data)
            
            embedding = await self._get_embedding_from_api(summary)
            
            # 存储结果
            self.agent_keywords[agent_aic] = keywords
            self.agent_summaries[agent_aic] = {
                'summary': summary,
                'mod_time': agent_mod_time,
                'build_time': datetime.now().isoformat()
            }
            self.agent_embeddings[agent_aic] = embedding
            
            self._save_cache()
            
            logger.info(f"智能体 {agent_aic} 索引更新成功")
                
        except Exception as e:
            logger.error(f"处理智能体 {agent_aic} 索引失败: {e}")


    def _extract_task_keywords(self, task_description: str, task_requirements: Optional[Dict] = None) -> Set[str]:
        """从任务描述中提取关键词"""
        keywords = set()
        
        # 从任务需求中提取
        if task_requirements:
            required_skills = task_requirements.get('required_skills', [])
            required_tools = task_requirements.get('required_tools', [])
            domain = task_requirements.get('domain', '')
            
            for skill in required_skills:
                keywords.update(self._extract_chinese_keywords(skill))
                keywords.update(self._extract_english_keywords(skill))
            
            for tool in required_tools:
                keywords.update(self._extract_chinese_keywords(tool))
                keywords.update(self._extract_english_keywords(tool))
            
            if domain:
                keywords.update(self._extract_chinese_keywords(domain))
                keywords.update(self._extract_english_keywords(domain))
        
        # 从任务描述中提取
        keywords.update(self._extract_chinese_keywords(task_description))
        keywords.update(self._extract_english_keywords(task_description))
        
        return keywords
    
    def _create_task_summary(self, task_description: str, task_requirements: Optional[Dict] = None) -> str:
        """创建任务摘要文本，用于生成embedding"""
        summary_parts = [f"任务描述: {task_description}"]
        
        if task_requirements:
            required_skills = task_requirements.get('required_skills', [])
            required_tools = task_requirements.get('required_tools', [])
            domain = task_requirements.get('domain', '')
            complexity = task_requirements.get('complexity', '')
            
            if required_skills:
                summary_parts.append(f"所需技能: {', '.join(required_skills)}")
            if required_tools:
                summary_parts.append(f"所需工具: {', '.join(required_tools)}")
            if domain:
                summary_parts.append(f"任务领域: {domain}")
            if complexity:
                summary_parts.append(f"复杂度: {complexity}")
        
        return "; ".join(summary_parts)
    
    async def calculate_semantic_similarity(self, 
                                    task_description: str, 
                                    task_requirements: Optional[Dict] = None,
                                    agent_aics: Optional[List[str]] = None) -> Dict[str, float]:
        """
        计算任务与智能体的语义相似度（使用API生成task embedding）
        
        Args:
            task_description: 任务描述
            task_requirements: 任务需求
            agent_aics: 要计算的智能体AIC列表，None表示计算所有
            
        Returns:
            {agent_aic: similarity_score} 字典
        """
        if not self.agent_embeddings:
            logger.warning("智能体embedding索引为空，请先调用build_agent_index")
            return {}
        
        # 创建任务摘要并生成embedding
        task_summary = self._create_task_summary(task_description, task_requirements)
        task_embedding = await self._get_embedding_from_api(task_summary)
        
        # 确定要计算的智能体列表
        target_aics = agent_aics or list(self.agent_embeddings.keys())
        
        similarities = {}
        
        for agent_aic in target_aics:
            if agent_aic not in self.agent_embeddings:
                continue
            
            try:
                # 计算基础相似度
                agent_embedding = self.agent_embeddings[agent_aic]
                base_similarity = cosine_similarity(
                    [task_embedding], [agent_embedding]
                )[0][0]
                
                # 计算关键词匹配加成
                task_keywords = self._extract_task_keywords(task_description, task_requirements)
                agent_keywords = self.agent_keywords.get(agent_aic, {})
                
                keyword_boost = self._calculate_keyword_boost(task_keywords, agent_keywords)
                
                # 计算最终得分
                final_score = base_similarity + keyword_boost
                final_score = max(0.0, min(1.0, final_score))
                
                similarities[agent_aic] = final_score
                
            except Exception as e:
                logger.error(f"计算智能体 {agent_aic} 相似度失败: {e}")
                similarities[agent_aic] = 0.0
        
        return similarities
    
    def _calculate_keyword_boost(self, task_keywords: Set[str], agent_keywords: Dict[str, List[str]]) -> float:
        """计算关键词匹配加成"""
        if not task_keywords:
            return 0.0
        
        config = self.semantic_config
        total_boost = 0.0
        
        # 精确匹配和部分匹配的权重
        exact_match_bonus = 0.1
        partial_match_bonus = 0.05
        
        for category, keywords in agent_keywords.items():
            if not keywords:
                continue
            
            category_weight = config.get(f"{category}_weight", 0.1)
            category_boost = 0.0
            
            for task_kw in task_keywords:
                for agent_kw in keywords:
                    if task_kw == agent_kw:  # 精确匹配
                        category_boost += exact_match_bonus
                    elif task_kw in agent_kw or agent_kw in task_kw:  # 部分匹配
                        category_boost += partial_match_bonus
            
            total_boost += category_boost * category_weight
        
        return min(total_boost, 0.3)  # 限制最大加成为0.3
    
    async def get_top_matches(self, 
                    task_description: str,
                    task_requirements: Optional[Dict] = None,
                    k: int = 10,
                    min_similarity: Optional[float] = None) -> List[Tuple[str, float]]:
        """
        获取最匹配的智能体
        
        Args:
            task_description: 任务描述
            task_requirements: 任务需求
            k: 返回前k个结果
            min_similarity: 最小相似度阈值
            
        Returns:
            [(agent_aic, similarity_score)] 列表，按相似度降序排列
        """
        similarities = await self.calculate_semantic_similarity(task_description, task_requirements)
        
        # 应用最小相似度阈值
        threshold = min_similarity or self.semantic_config["min_similarity"]
        filtered_similarities = {
            aic: score for aic, score in similarities.items() 
            if score >= threshold
        }
        
        # 排序并返回前k个
        sorted_matches = sorted(
            filtered_similarities.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        return sorted_matches[:k]
    
    async def explain_match(self, agent_aic: str, task_description: str, task_requirements: Optional[Dict] = None) -> Dict[str, Any]:
        """
        解释智能体与任务的匹配情况
        
        Args:
            agent_aic: 智能体AIC
            task_description: 任务描述
            task_requirements: 任务需求
            
        Returns:
            匹配解释字典
        """
        if agent_aic not in self.agent_embeddings:
            return {"error": f"智能体 {agent_aic} 未建立索引"}
        
        # 计算相似度
        similarities = await self.calculate_semantic_similarity(task_description, task_requirements, [agent_aic])
        similarity_score = similarities.get(agent_aic, 0.0)
        
        # 获取关键词信息
        task_keywords = self._extract_task_keywords(task_description, task_requirements)
        agent_keywords = self.agent_keywords.get(agent_aic, {})
        agent_summary = self.agent_summaries.get(agent_aic, {}).get('summary', '')
        
        # 分析匹配的关键词
        matched_keywords = {}
        for category, keywords in agent_keywords.items():
            matches = []
            for task_kw in task_keywords:
                for agent_kw in keywords:
                    if task_kw == agent_kw or task_kw in agent_kw or agent_kw in task_kw:
                        matches.append((task_kw, agent_kw))
            if matches:
                matched_keywords[category] = matches
        
        explanation = {
            "agent_aic": agent_aic,
            "similarity_score": similarity_score,
            "agent_summary": agent_summary,
            "task_keywords": list(task_keywords),
            "agent_keywords": agent_keywords,
            "matched_keywords": matched_keywords,
            "match_level": (
                "高度匹配" if similarity_score >= 0.7 else
                "较好匹配" if similarity_score >= 0.5 else  
                "一般匹配" if similarity_score >= 0.3 else
                "较低匹配"
            )
        }
        
        return explanation
    
    def update_semantic_config(self, **kwargs):
        """更新语义匹配配置"""
        self.semantic_config.update(kwargs)
        logger.info(f"语义匹配配置已更新: {self.semantic_config}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_agents": len(self.agent_embeddings),
            "cache_files": {
                "embeddings": os.path.exists(self.embeddings_cache_file),
                "keywords": os.path.exists(self.keywords_cache_file),
                "summaries": os.path.exists(self.summaries_cache_file)
            },
            "model_info": {
                "model_name": self.model_name,
                "api_endpoint": self.api_endpoint
            },
            "config": self.semantic_config.copy()
        }