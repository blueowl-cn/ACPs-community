import json
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
import asyncio
import aiohttp
import os
from datetime import datetime
from pathlib import Path
from app.discovery.semantic_matcher import SemanticAgentMatcher, SkillSemanticMatcher
import jieba
import time
from datetime import datetime

class EnhancedAgentDiscoverySystem:
    """增强的智能体发现系统"""
    
    def __init__(self, api_key: str = None, api_endpoint: str = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"):
        self.agents = []
        self.api_endpoint = api_endpoint
        self.api_key = api_key or os.getenv('DASHSCOPE_API_KEY')
        # 组件初始化
        script_path = Path(__file__).resolve()
        script_dir = script_path.parent

        self.datalog_dir = script_dir / "datalog"
        self.datalog_dir.mkdir(exist_ok=True, parents=True)
        
        self.current_log_data = None
        self.current_log_file = None

        # 加权评分配置
        self.scoring_config = {
            "llm_score_weight": 1.0,         # LLM评分权重
        }
        
        # 优化配置
        self.optimization_config = {
            "max_agents_to_llm": 20,         # 发送给LLM的最大数量
            "llm_return_multiplier": 1,      # LLM返回数量是k的几倍
            "prefilter_enabled": True,       # 是否启用预筛选
            "use_semantic_matching": True,  # 启用语义匹配
            "semantic_weight": 25,           # 语义匹配权重
            "keyword_weight": 3,            # 关键词匹配权重
            "relevance_threshold": 0.4,      # 相关性阈值
            "use_skill_semantic": True,      # 启用技能级语义匹配
            "skill_semantic_weight": 100,     # 技能语义匹配权重            
        }

        # 可选的语义匹配器
        if self.optimization_config.get("use_semantic_matching", False):
            try:
                semantic_cache_dir = script_dir / "semantic_cache"
                self.semantic_matcher = SemanticAgentMatcher(
                    cache_dir=semantic_cache_dir,
                    similarity_threshold=0.3
                )
            except:
                print("语义匹配器初始化失败，将使用传统匹配")
                self.optimization_config["use_semantic_matching"] = False
                self.semantic_matcher = None
        
        if self.optimization_config.get("use_skill_semantic", False):
            try:
                skill_semantic_cache_dir = script_dir / "skill_semantic_cache"
                self.skill_semantic_matcher = SkillSemanticMatcher(
                    cache_dir=skill_semantic_cache_dir
                )
            except Exception as e:
                print(f"技能级语义匹配器初始化失败: {e}，将使用传统匹配")
                self.optimization_config["use_skill_semantic"] = False
                self.skill_semantic_matcher = None

    def _init_log_session(self, task_description: str, task_requirements: Optional[Dict] = None, k: int = 5):
        """初始化一个新的日志会话"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] 
        self.current_log_file = self.datalog_dir / f"{timestamp}.log"
        
        self.current_log_data = {
            "session_id": timestamp,
            "start_time": datetime.now().isoformat(),
            "input": {
                "task_description": task_description,
                "task_requirements": task_requirements,
                "k": k
            },
            "config": {
                "scoring_config": self.scoring_config.copy(),
                "optimization_config": self.optimization_config.copy()
            },
            "process_steps": {},
            "intermediate_results": {},
            "output": None,
            "end_time": None,
            "total_time": None,
            "error": None
        }

    def _log_step(self, step_name: str, data: Dict[str, Any]):
        """记录处理步骤"""
        if self.current_log_data:
            self.current_log_data["process_steps"][step_name] = {
                "timestamp": datetime.now().isoformat(),
                "data": data
            }

    def _log_intermediate_result(self, key: str, value: Any):
        """记录中间结果"""
        if self.current_log_data:
            self.current_log_data["intermediate_results"][key] = value

    def _save_log(self):
        """保存日志到文件"""
        if not self.current_log_data or not self.current_log_file:
            return
        
        try:
            # 添加结束时间和总耗时
            self.current_log_data["end_time"] = datetime.now().isoformat()
            start = datetime.fromisoformat(self.current_log_data["start_time"])
            end = datetime.fromisoformat(self.current_log_data["end_time"])
            self.current_log_data["total_time"] = (end - start).total_seconds()
            
            # 写入日志文件
            with open(self.current_log_file, 'w', encoding='utf-8') as f:
                json.dump(self.current_log_data, f, ensure_ascii=False, indent=2)
            
            print(f"📝 日志已保存: {self.current_log_file.name}")
        except Exception as e:
            print(f"⚠️ 保存日志失败: {e}")


    async def _prefilter_skills_with_semantic(self, task_description: str, skill_candidates: List[Dict],
                        task_requirements: Optional[Dict] = None, 
                        max_candidates: int = 50) -> List[Dict]:
        """技能级别的预筛选（增强版：关键词 + 语义相似度）"""
        if not self.optimization_config["prefilter_enabled"] or len(skill_candidates) <= max_candidates:
            return skill_candidates
        
        print(f"🔍 启动增强技能预筛选：从 {len(skill_candidates)} 个技能中筛选最多 {max_candidates} 个")
        
        # 提取任务关键词
        task_keywords = self._extract_keywords_from_task(task_description, task_requirements)
        print(f"🔑 提取的关键词: {list(task_keywords)[:10]}...")
        
        # 计算技能语义相似度（如果启用）
        skill_semantic_scores = {}
        if self.optimization_config.get("use_skill_semantic", False) and self.skill_semantic_matcher:
            try:
                print(f"🧠 计算技能级语义相似度...")
                skill_semantic_scores = await self.skill_semantic_matcher.calculate_skills_similarity(
                    task_description=task_description,
                    task_requirements=task_requirements,
                    skills=skill_candidates
                )
                print(f"✅ 技能语义相似度计算完成: {len(skill_semantic_scores)} 个技能")
            except Exception as e:
                print(f"⚠️ 技能语义相似度计算失败: {e}")
                skill_semantic_scores = {}
        
        scored_skills = []
        semantic_weight = self.optimization_config.get("skill_semantic_weight", 15)
        
        for skill in skill_candidates:
            # 计算关键词得分
            keyword_score = self._calculate_skill_prefilter_score(skill, task_keywords, task_requirements)
            
            # 获取语义相似度得分
            skill_key = self._get_skill_key(skill)
            semantic_score = skill_semantic_scores.get(skill_key, 0.0)
            
            # 加权组合得分
            final_score = keyword_score + (semantic_score * semantic_weight)
            
            scored_skills.append((skill, final_score, keyword_score, semantic_score))
        
        # 按最终得分排序并取前N个
        scored_skills.sort(key=lambda x: x[1], reverse=True)
        filtered_skills = [skill for skill, final_score, kw_score, sem_score in scored_skills[:max_candidates]]
        
        print(f"✅ 技能预筛选完成：保留 {len(filtered_skills)} 个候选技能")
        if scored_skills:
            top_item = scored_skills[0]
            bottom_item = scored_skills[-1]
            print(f"📊 得分范围: {bottom_item[1]:.1f} ~ {top_item[1]:.1f}")
            print(f"   (关键词: {bottom_item[2]:.1f}~{top_item[2]:.1f}, 语义: {bottom_item[3]:.3f}~{top_item[3]:.3f})")

        print("最终候选技能:")
        for i, (skill, final_score, kw_score, sem_score) in enumerate(scored_skills[:max_candidates], 1):
            print(f"{i}. {skill.get('skill_name', '未知')} (Agent: {skill.get('agent_name', '未知')}) "
                f"- 总分:{final_score:.1f} (关键词:{kw_score:.1f}, 语义:{sem_score:.3f})")

        return filtered_skills

    def _get_skill_key(self, skill: Dict) -> str:
        """生成技能的唯一标识符"""
        aic = skill.get('aic', '')
        skillid = skill.get('skillid', '')
        if not skillid:
            return f"{aic}@agent"
        return f"{aic}_{skillid}"

    def _extract_agent_url(self, agent: Dict[str, Any]) -> str:
        """从新的ACS结构中提取Agent的URL"""

        endpoints = agent.get('endPoints', [])
        if endpoints and len(endpoints) > 0:
            return endpoints[0].get('url', '')
        

        web_app_url = agent.get('webAppUrl', '')
        if web_app_url:
            return web_app_url
            

        doc_url = agent.get('documentationUrl', '')
        if doc_url:
            return doc_url
            
        return ''

    async def load_agents_async(self, agents_data: List[Dict[str, Any]]):
        """加载智能体数据（异步版本，自动构建语义索引）"""
        self.agents = agents_data
        print(f"已加载 {len(self.agents)} 个智能体")
        
        # 构建语义索引（如果启用）
        if self.optimization_config.get("use_semantic_matching", False) and self.semantic_matcher:
            print("构建智能体语义索引...")
            try:
                await self.semantic_matcher.build_agent_index(self.agents)
                print("✅ 语义索引构建完成")
            except Exception as e:
                print(f"❌ 语义索引构建失败: {e}")
                import traceback
                traceback.print_exc()
                self.optimization_config["use_semantic_matching"] = False
    
    def _extract_agent_skills_and_tags(self, agent: Dict[str, Any]) -> Tuple[List[str], List[str], List[str]]:
        """从标准格式智能体中提取技能、标签和能力信息"""
        skills = []
        tags = []
        capabilities = []
        
        # 从skills数组中提取信息
        for skill in agent.get('skills', []):
            # 技能名称
            if skill.get('name'):
                skills.append(skill['name'].lower())
            
            # 技能标签
            skill_tags = skill.get('tags', [])
            if isinstance(skill_tags, list):
                tags.extend([tag.lower() for tag in skill_tags])
            
            # 技能描述作为能力
            if skill.get('description'):
                capabilities.append(skill['description'].lower())
            
            # 输入输出类型也可作为能力
            input_modes = skill.get('inputModes', [])
            output_modes = skill.get('outputModes', [])
            capabilities.extend([imode.lower() for imode in input_modes])
            capabilities.extend([omode.lower() for omode in output_modes])
        
        return skills, tags, capabilities
    
    def _extract_keywords_from_task(self, task_description: str, task_requirements: Optional[Dict] = None) -> set:
        """从任务描述和需求中提取关键词（中文jieba分词优化版）"""
        keywords = set()
        
        # 任务需求
        if task_requirements:
            keywords.update([skill.lower() for skill in task_requirements.get('required_skills', [])])
            keywords.update([tool.lower() for tool in task_requirements.get('required_tools', [])])
            if task_requirements.get('domain'):
                keywords.add(task_requirements['domain'].lower())
        
        # 使用jieba分词处理中文任务描述
        task_description = task_description.lower()
        seg_list = jieba.lcut(task_description)
        
        # 停用词
        stop_words = {'的', '和', '或', '但是', '因为', '所以', '我', '你', '他', '她', '它', '我们', '你们', '他们',
                    '了', '在', '是', '有', '给', '一些', '请', '帮', '找', '做', '就', '都'}
        
        # 筛选有效关键词（长度大于1，非停用词）
        keywords.update([word for word in seg_list if len(word) > 1 and word not in stop_words])
        
        return keywords
    
    
    
    def _calculate_enhanced_weighted_score(self, agent_aic: str, llm_score: float) -> Tuple[float, Dict[str, float]]:
        """
        计算增强的加权得分，初版仅计算llm_score部分，后续可添加更多维度
        
        Args:
            agent_aic: 智能体AIC
            llm_score: LLM给出的基础得分
            
        Returns:
            (最终加权得分, 得分组成详情)
        """
        config = self.scoring_config
        
        # 1. LLM评分组件
        llm_component = llm_score * config["llm_score_weight"]
        
        weighted_score = llm_component

        # 确保得分在合理范围内
        weighted_score = max(0.0, min(1.0, weighted_score))
        
        # 返回得分详情
        score_details = {
            "llm_score": llm_score,
            "llm_component": llm_component,
            "final_weighted_score": weighted_score,
        }
        
        return weighted_score, score_details
    
    async def _call_llm_api(self, prompt: str) -> str:
        """调用QWEN API"""
        if not self.api_key:
            raise ValueError("API密钥未设置")
            
        print(" 正在调用QWEN API...")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": "qwen-plus",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "temperature": 0.1,
            "stream": False
        }
        
        async with aiohttp.ClientSession() as session:
            print("  发送请求到QWEN API...")
            async with session.post(self.api_endpoint, headers=headers, json=payload) as response:
                print(f"  收到响应，状态码: {response.status}")
                
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"QWEN API错误 ({response.status}): {error_text}")
                
                result = await response.json()
                print("QWEN API调用成功")
                
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    print(f"  收到响应长度: {len(content)} 字符")
                    return content
                else:
                    raise Exception("QWEN API响应格式异常")
    
    
    def _expand_agents_to_skills(self, agents: List[Dict]) -> List[Dict]:
        """把Agent展开为Skill候选列表，增强版本
        
        处理逻辑：
        1. 有技能的Agent：展开为多个skill候选
        2. 无技能的Agent：转换为单个skill候选（继承Agent描述）
        """
        skill_candidates = []
        
        for agent in agents:
            # 提取Agent公共信息
            agent_aic = agent.get("aic", "")
            agent_url = self._extract_agent_url(agent)
            agent_name = agent.get("name", "")
            agent_description = agent.get("description", "")
            agent_status = "active" if agent.get("active", False) else "inactive"
            provider_info = agent.get("provider", {})
            
            skills = agent.get("skills", [])
            
            # 关键改进：处理空技能列表
            if not skills:
                # 将Agent本身作为一个skill候选
                skill_candidate = {
                    # 基础信息
                    "aic": agent_aic,
                    "url": agent_url,
                    "skillid": "",  # 空skillid标识这是Agent级能力
                    "skill_name": "",  # 空技能名
                    "description": agent_description,  # 继承Agent描述
                    
                    # 技能详细信息（使用默认值）
                    "tags": agent.get("tags", []),  # 尝试继承Agent的tags
                    "inputTypes": [],
                    "outputTypes": [],
                    "version": agent.get("version", ""),
                    "examples": [],
                    
                    # Agent信息
                    "agent_name": agent_name,
                    "agent_description": agent_description,
                    "agent_status": agent_status,
                    "provider": provider_info,
                    
                    # 标记为Agent级能力
                    "parent_agent": agent,
                    "is_agent_level_skill": True  # 新增标记字段
                }
                skill_candidates.append(skill_candidate)
            else:
                # 原有逻辑：展开具体技能
                for skill in skills:
                    skill_candidate = {
                        # 基础信息
                        "aic": agent_aic,
                        "url": agent_url,
                        "skillid": skill.get("id", ""),
                        "skill_name": skill.get("name", ""),
                        "description": skill.get("description", ""),
                        
                        # 技能详细信息
                        "tags": skill.get("tags", []),
                        "inputTypes": skill.get("inputModes", []),
                        "outputTypes": skill.get("outputModes", []),
                        "version": skill.get("version", ""),
                        "examples": skill.get("examples", []),
                        
                        # Agent信息
                        "agent_name": agent_name,
                        "agent_description": agent_description,
                        "agent_status": agent_status,
                        "provider": provider_info,
                        
                        # 完整Agent信息
                        "parent_agent": agent,
                        "is_agent_level_skill": False
                    }
                    skill_candidates.append(skill_candidate)
        
        return skill_candidates
    

    def _calculate_skill_prefilter_score(
        self,
        skill: Dict,
        task_keywords: set,
        task_requirements: Optional[Dict] = None
    ) -> float:
        """计算技能级别的预筛选得分（支持中文分词 + Agent级能力）"""
        score = 0.0
        config = self.optimization_config


        text_parts = []

        if skill.get("agent_name"):
            text_parts.append(skill["agent_name"])
        if skill.get("agent_description"):
            text_parts.append(skill["agent_description"])

        # Skill 级信息
        if skill.get("skill_name"):
            text_parts.append(skill["skill_name"])
        if skill.get("description"):
            text_parts.append(skill["description"])

        # Tags / IO Types
        text_parts.extend(skill.get("tags", []) or [])
        text_parts.extend(skill.get("inputTypes", []) or [])
        text_parts.extend(skill.get("outputTypes", []) or [])

        full_text = " ".join(text_parts).lower()

        # 加入 jieba 分词
        skill_tokens = {
            w for w in jieba.lcut(full_text)
            if len(w) >= 2   
        }

        keyword_matches = sum(1 for kw in task_keywords if kw in skill_tokens)
        score += keyword_matches * config["keyword_weight"]


        return score

    
    def _prefilter_skills(self, task_description: str, skill_candidates: List[Dict],
                         task_requirements: Optional[Dict] = None, 
                         max_candidates: int = 50) -> List[Dict]:
        """技能级别的预筛选"""
        if not self.optimization_config["prefilter_enabled"] or len(skill_candidates) <= max_candidates:
            return skill_candidates
        
        print(f"🔍 启动技能级预筛选：从 {len(skill_candidates)} 个技能中筛选最多 {max_candidates} 个")
        
        # 提取任务关键词
        task_keywords = self._extract_keywords_from_task(task_description, task_requirements)
        print(f"🔑 提取的关键词: {list(task_keywords)[:10]}...")
        
        scored_skills = []
        
        for skill in skill_candidates:
            score = self._calculate_skill_prefilter_score(skill, task_keywords, task_requirements)
            scored_skills.append((skill, score))
        
        # 按得分排序并取前N个
        scored_skills.sort(key=lambda x: x[1], reverse=True)
        filtered_skills = [skill for skill, score in scored_skills[:max_candidates]]
        
        print(f"✅ 技能预筛选完成：保留 {len(filtered_skills)} 个候选技能")
        if scored_skills:
            print(f"📊 得分范围: {scored_skills[-1][1]:.1f} ~ {scored_skills[0][1]:.1f}")

        print("最终候选技能:")
        for skill in filtered_skills:
            print(f"- {skill.get('skill_name', '未知')} (Agent: {skill.get('agent_name', '未知')})")        

        return filtered_skills


    def _prepare_skill_info_enhanced(self, skills_list: List[Dict]) -> str:
        """准备增强的技能级别提示信息"""
        info_list = []
        for i, skill in enumerate(skills_list, 1):
            # 构建技能详细信息
            skill_info = f"""
技能{i}: {skill.get('skill_name', '未知')} (SkillID: {skill.get('skillid', '未知')})
- 所属Agent: {skill.get('agent_name', '未知')} (AIC: {skill.get('aic', '未知')})
- Agent URL: {skill.get('url', '未知')}
- 技能描述: {skill.get('description', '无')}
- 技能标签: {', '.join(skill.get('tags', [])) if skill.get('tags') else '无'}
- 输入类型: {', '.join(skill.get('inputTypes', [])) if skill.get('inputTypes') else '无'}
- 输出类型: {', '.join(skill.get('outputTypes', [])) if skill.get('outputTypes') else '无'}
- 技能版本: {skill.get('version', '未知')}
- Agent状态: {skill.get('agent_status', '未知')}
- 提供商: {skill.get('provider', {}).get('organization', '未知')}"""
            
            # 添加使用示例（如果有）
            examples = skill.get('examples', [])
            if examples:
                skill_info += f"\n- 使用示例: {examples[0]}"
            
                
            info_list.append(skill_info)
        
        return "\n\n---\n\n".join(info_list)

    def _prepare_skill_info_for_llm(self, skills_list: List[Dict]) -> str:
        """为LLM准备高度精简的技能信息 (JSON格式)"""
        compact_skills = []
        for i, skill in enumerate(skills_list, 1):
            # 将输入输出类型简化为一行
            input_str = ','.join(skill.get('inputTypes', []))
            output_str = ','.join(skill.get('outputTypes', []))
            io_str = f"in:[{input_str}] -> out:[{output_str}]"
            
            compact_skills.append({
                "id": i, # 使用数字ID，更简短
                "aic": skill.get('aic', '未知'),
                "skillid": skill.get('skillid', '未知'),
                "name": skill.get('skill_name', '未知'),
                "desc": skill.get('description', '无'),
                "tags": skill.get('tags', []),
                "io": io_str
            })
        # 返回紧凑的JSON字符串
        return json.dumps(compact_skills, ensure_ascii=False, separators=(',', ':'))

    def _create_skill_evaluation_prompt_enhanced(self, task_description: str,
                                                task_requirements: Optional[Dict[str, Any]] = None,
                                                k: int = 5,
                                                candidate_skills: List[Dict] = None) -> str:
        """创建增强的基于技能的评估提示词"""
        
        skills_to_evaluate = candidate_skills or []
        skill_info = self._prepare_skill_info_enhanced(skills_to_evaluate)
        # 计算LLM应该返回的技能数量
        llm_return_count = min(
            k * self.optimization_config["llm_return_multiplier"],
            len(skills_to_evaluate)
        )
        
        requirements_str = ""
        if task_requirements:
            requirements_str = f"""
明确的任务需求:
- 所需技能: {', '.join(task_requirements.get('required_skills', []))}
- 任务领域: {task_requirements.get('domain', '未指定')}
- 复杂度: {task_requirements.get('complexity', '未指定')}
- 所需工具: {', '.join(task_requirements.get('required_tools', []))}
- 输入数据类型: {', '.join(task_requirements.get('input_types', []))}
- 输出数据类型: {', '.join(task_requirements.get('output_types', []))}
- 紧急程度: {task_requirements.get('urgency', '未指定')}
            """.strip()

        prompt = f"""
你是一个专业的AI技能匹配专家。请根据以下任务描述和技能信息，选出最匹配的 {llm_return_count} 个技能。

任务描述:
{task_description}

{requirements_str}

候选技能信息（已预筛选）:
{skill_info}

**重要指示：请专注于技能级别的匹配，评估每个技能与任务的具体适配性。**

请分析每个技能与任务的匹配程度，考虑以下因素:
1. 技能功能匹配度 - 技能提供的功能是否满足任务具体需求
2. 数据类型兼容性 - 技能的输入输出类型是否与任务数据兼容
3. 技能精确性 - 技能描述与任务需求的精确匹配程度
4. 技术栈适配 - 技能的技术实现是否适合任务场景
5. 可用性和稳定性 - 所属Agent的状态和技能的成熟度
6. 易用性 - 技能的使用复杂度和文档完整性

请以JSON格式返回评估结果，只包含最匹配的 {llm_return_count} 个技能：

{{
  "task_analysis": {{
    "main_skill_requirements": ["核心技能需求1", "核心技能需求2"],
    "complexity_level": "low/medium/high",
    "primary_domain": "主要技术领域",
    "required_data_flow": "输入类型 -> 处理过程 -> 输出类型",
    "performance_expectations": "性能期望描述"
  }},
  "skill_evaluations": [
    {{
      "aic": "所属Agent的AIC",
      "skillid": "技能ID",
      "skill_name": "技能名称",
      "overall_score": 0.85,
      "detailed_scores": {{
        "function_match": 0.9,
        "data_compatibility": 0.8,
        "precision_match": 0.9,
        "tech_stack_fit": 0.8,
        "availability": 0.85,
        "usability": 0.75
      }},
      "matching_features": ["匹配的功能特性1", "匹配的功能特性2"],
      "data_flow_analysis": {{
        "input_compatibility": "输入兼容性分析",
        "output_suitability": "输出适用性分析",
        "processing_efficiency": "处理效率评估"
      }},
      "strengths": ["该技能的优势1", "该技能的优势2"],
      "limitations": ["技能局限性1", "技能局限性2"],
      "recommendation_reason": "推荐该技能的详细理由",
      "confidence_level": "high/medium/low",
      "estimated_performance": "性能估计描述"
    }}
  ],
  "skill_ranking": [
    {{
      "rank": 1,
      "aic": "最佳匹配技能所属Agent的AIC",
      "skillid": "最佳匹配的技能ID",
      "score": 0.85,
      "brief_reason": "简短的推荐理由"
    }}
  ],
  "evaluation_metadata": {{
    "total_skills_considered": {len(skills_to_evaluate)},
    "top_skills_returned": {llm_return_count},
    "evaluation_focus": "skill_level_matching",
    "matching_strategy": "precision_over_coverage"
  }}
}}

要求:
1. 专注于技能级别的精确匹配，而不是Agent级别的泛化能力
2. 评分范围0-1，保留2位小数
3. 按总分从高到低排序技能
4. **只返回最匹配的 {llm_return_count} 个技能的详细信息**
5. 推荐理由要基于技能的具体功能特性
6. 确保使用正确的AIC和技能ID格式
7. 分析数据流的兼容性和处理效率

请确保返回纯净的JSON格式，不要包含任何额外的文本或代码块标记。
        """.strip()
        
        return prompt


    def _create_skill_evaluation_prompt_simplified(self, task_description: str,
                                                task_requirements: Optional[Dict[str, Any]] = None,
                                                k: int = 5,
                                                candidate_skills: List[Dict] = None) -> str:
        """创建极简的、用于技能评估的提示词"""
        
        skills_to_evaluate = candidate_skills or []
        # 使用新的、精简的方法
        skill_info_json = self._prepare_skill_info_for_llm(skills_to_evaluate)
        
        # LLM需要返回的数量
        llm_return_count = min(
            k * self.optimization_config["llm_return_multiplier"],
            len(skills_to_evaluate)
        )

        prompt = f"""
    你是一个AI技能匹配专家。根据任务描述，对候选技能进行评分和排序。

    [任务描述]
    {task_description}

    [候选技能列表 (JSON格式)]
    {skill_info_json}

    [评分规则]
    - 对于与任务高度相关的技能：给予 0.6-1.0 分
    - 对于与任务部分相关的技能：给予 0.4-0.6 分
    - 对于与任务基本不相关的技能：给予 0.0-0.4 分（低相关性）

    ⚠️ 重要：请严格评估相关性。如果技能的功能、输入输出类型、应用场景与任务需求不匹配，必须给予低分（<0.4）。

    [你的任务]
    1. 评估每个技能与任务的实际匹配程度
    2. 为每个技能给出 0.0-1.0 的分数，必须真实反映相关性
    3. 按分数从高到低排序
    4. 返回前 {llm_return_count} 个技能的评估结果
    5. **总结你的选择思路：为什么选择这些技能？为什么排除其他技能？**

    [输出格式]
    严格按照以下JSON格式返回，不要添加任何解释文字或代码块标记：

    {{
    "reasoning": "你对技能选择和排除的整体思路总结（要求100字以内），包括：1）对任务核心需求的理解；2）选中技能的共同特点；3）排除技能的主要原因",
    "skills": [
        {{
        "aic": "aic-of-skill",
        "skillid": "skillid-of-skill",
        "score": 0.95,
        "reason": "该技能的核心功能与任务要求高度吻合。"
        }},
        {{
        "aic": "another-aic",
        "skillid": "another-skillid",
        "score": 0.15,
        "reason": "技能功能与任务需求不相关，输入输出类型不匹配。"
        }}
    ]
    }}

    注意：
    1. reasoning字段必须提供，简明扼要地总结选择逻辑
    2. 如果所有技能都不相关，也请如实说明并给出低分（<0.4）
    """
        return prompt.strip()



    async def discover_skills_enhanced(self, task_description: str,
                                        task_requirements: Optional[Dict[str, Any]] = None,
                                        k: int = 5) -> Dict[str, Any]:
        """
        (优化版) 基于技能的智能体发现方法，采用精简Prompt和响应格式。
        """
        self._init_log_session(task_description, task_requirements, k)
        
        if not self.agents:
            error_result = {"error": "没有可用的智能体"}
            self.current_log_data["error"] = "没有可用的智能体"
            self.current_log_data["output"] = error_result
            self._save_log()
            return error_result

        try:
            total_start = time.time()
            print(f"\n🔍 [START] 启动基于技能的增强发现 (k={k}) @ {datetime.now().strftime('%H:%M:%S')}")

            # 步骤1: 展开所有技能
            t1 = time.time()
            all_skills = self._expand_agents_to_skills(self.agents)
            step1_time = time.time() - t1
            print(f"📋 [Step1] 展开技能完成: {len(all_skills)} 个技能，用时 {step1_time:.3f}s")
            
            self._log_step("step1_expand_skills", {
                "total_skills": len(all_skills),
                "time_cost": step1_time,
                "agent_level_skills": sum(1 for s in all_skills if s.get('is_agent_level_skill', False)),
                "specific_skills": sum(1 for s in all_skills if not s.get('is_agent_level_skill', False))
            })

            # 步骤2: 技能级预筛选
            t2 = time.time()
            num = min((self.optimization_config["max_agents_to_llm"]),
                    (k * (self.optimization_config["llm_return_multiplier"] + 1)))
            candidate_skills = await self._prefilter_skills_with_semantic(
                task_description,
                all_skills,
                task_requirements,
                num
            )
            step2_time = time.time() - t2
            print(f"⚙️ [Step2] 技能预筛选完成: {len(candidate_skills)} 个候选，用时 {step2_time:.3f}s")
            
            self._log_step("step2_prefilter", {
                "input_skills": len(all_skills),
                "output_candidates": len(candidate_skills),
                "target_max": num,
                "time_cost": step2_time,
                "reduction_ratio": 1 - (len(candidate_skills) / len(all_skills)) if all_skills else 0,
                "candidates": [
                    {
                        "aic": s.get("aic"),
                        "skillid": s.get("skillid"),
                        "skill_name": s.get("skill_name"),
                        "agent_name": s.get("agent_name"),
                        "is_agent_level": s.get("is_agent_level_skill", False)
                    }
                    for s in candidate_skills
                ]
            })

            # 步骤3: 构造提示词
            t3 = time.time()
            prompt = self._create_skill_evaluation_prompt_simplified(
                task_description,
                task_requirements,
                k,
                candidate_skills
            )
            step3_time = time.time() - t3
            print(f"🧠 [Step3] 构造Prompt完成（长度={len(prompt)}），用时 {step3_time:.3f}s")
            
            self._log_step("step3_create_prompt", {
                "prompt_length": len(prompt),
                "time_cost": step3_time,
                "llm_return_count": min(k * self.optimization_config["llm_return_multiplier"], len(candidate_skills)),
                "prompt_preview": prompt[:500] + "..." if len(prompt) > 500 else prompt
            })

            # 步骤4: 调用 LLM
            t4 = time.time()
            print(f"📤 [Step4] 发送 {len(candidate_skills)} 个候选技能给LLM评估 ...")
            response = await self._call_llm_api(prompt)
            llm_cost = time.time() - t4
            print(f"📥 [Step4] LLM响应接收完成，用时 {llm_cost:.3f}s")
            
            self._log_step("step4_llm_evaluation", {
                "candidates_sent": len(candidate_skills),
                "time_cost": llm_cost,
                "response_length": len(response),
                "response_preview": response[:500] + "..." if len(response) > 500 else response
            })

            # 步骤5: 解析响应
            t5 = time.time()
            response_text = response.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            llm_response = json.loads(response_text)
            
            # 提取 reasoning 和 skills
            llm_reasoning = llm_response.get("reasoning", "")
            llm_ranked_skills = llm_response.get("skills", [])
            
            step5_time = time.time() - t5
            print(f"📊 [Step5] 解析LLM响应成功: {len(llm_ranked_skills)} 项，用时 {step5_time:.3f}s")
            if llm_reasoning:
                print(f"💭 [Reasoning] {llm_reasoning[:100]}...")
            
            self._log_step("step5_parse_response", {
                "time_cost": step5_time,
                "llm_returned_count": len(llm_ranked_skills),
                "reasoning": llm_reasoning,
                "parsed_skills": llm_ranked_skills
            })

            # 步骤5.5: LLM得分过滤
            t5_5 = time.time()
            llm_score_threshold = self.optimization_config.get("relevance_threshold", 0.4)
            
            filtered_llm_skills = [
                item for item in llm_ranked_skills 
                if item.get("score", 0.0) >= llm_score_threshold
            ]
            
            excluded_count = len(llm_ranked_skills) - len(filtered_llm_skills)
            step5_5_time = time.time() - t5_5
            
            if excluded_count > 0:
                print(f"🔽 [Step5.5] LLM得分过滤: 排除 {excluded_count} 个低分技能（阈值={llm_score_threshold}）")
                if filtered_llm_skills:
                    print(f"   保留范围: {filtered_llm_skills[-1].get('score', 0):.3f} - {filtered_llm_skills[0].get('score', 0):.3f}")
            else:
                print(f"✅ [Step5.5] LLM得分过滤: 所有技能均通过阈值检查（阈值={llm_score_threshold}）")
            
            self._log_step("step5.5_threshold_filter", {
                "time_cost": step5_5_time,
                "threshold": llm_score_threshold,
                "before_filter": len(llm_ranked_skills),
                "after_filter": len(filtered_llm_skills),
                "excluded_count": excluded_count,
                "excluded_skills": [
                    {"aic": item.get("aic"), "skillid": item.get("skillid"), "score": item.get("score")}
                    for item in llm_ranked_skills if item.get("score", 0.0) < llm_score_threshold
                ]
            })

            # 如果全部被过滤，提前返回
            if not filtered_llm_skills:
                print(f"⚠️ [Step5.5] 所有技能的LLM得分均低于阈值 {llm_score_threshold}")
                highest_score = max([item.get("score", 0.0) for item in llm_ranked_skills]) if llm_ranked_skills else 0.0
                error_result = {
                    "skills": [],
                    "message": f"未找到符合LLM评分要求的技能（最高分: {highest_score:.3f}, 阈值: {llm_score_threshold}）",
                    "scoring_method": "enhanced_skill_based_discovery_optimized",
                    "optimization_stats": {
                        "original_skill_count": len(all_skills),
                        "candidates_sent_to_llm": len(candidate_skills),
                        "llm_returned_count": len(llm_ranked_skills),
                        "llm_filtered_count": 0,
                        "llm_score_threshold": llm_score_threshold,
                        "highest_llm_score": highest_score
                    }
                }
                self.current_log_data["output"] = error_result
                self._save_log()
                return error_result

            # 步骤6: 增强加权得分
            t6 = time.time()
            semantic_scores_map = {}
            if self.optimization_config.get("use_semantic_matching", False) and self.semantic_matcher:
                try:
                    all_aics = list(set([item.get("aic") for item in filtered_llm_skills]))
                    print(f"🧠 批量计算 {len(all_aics)} 个智能体的语义相似度...")
                    semantic_scores_map = await self.semantic_matcher.calculate_semantic_similarity(
                        task_description,
                        task_requirements,
                        all_aics
                    )
                    print(f"✅ 语义相似度计算完成")
                except Exception as e:
                    print(f"⚠️ 批量语义匹配失败: {e}")
                    semantic_scores_map = {}
            
            processed_evaluations = []
            for llm_item in filtered_llm_skills:
                aic = llm_item.get("aic")
                skillid = llm_item.get("skillid")
                llm_score = llm_item.get("score", 0.0)

                weighted_score, score_details = self._calculate_enhanced_weighted_score(aic, llm_score)

                if semantic_scores_map:
                    semantic_score = semantic_scores_map.get(aic, 0.0)
                    score_details["semantic_similarity"] = semantic_score
                    semantic_component = semantic_score * (self.optimization_config.get("semantic_weight", 25) / 100.0)
                    score_details["semantic_component"] = semantic_component
                    weighted_score = min(1.0, weighted_score + semantic_component)

                eval_item = llm_item.copy()
                eval_item["original_llm_score"] = llm_score
                eval_item["enhanced_weighted_score"] = weighted_score
                eval_item["scoring_details"] = score_details
                
                matching_skill = next(
                    (s for s in candidate_skills if s.get("aic") == aic and s.get("skillid") == skillid), None
                )
                if matching_skill:
                    eval_item["full_skill_info"] = matching_skill
                    eval_item["parent_agent_info"] = matching_skill.get("parent_agent")

                processed_evaluations.append(eval_item)

            step6_time = time.time() - t6
            print(f"📈 [Step6] 增强得分计算完成: {len(processed_evaluations)} 项，用时 {step6_time:.3f}s")
            
            self._log_step("step6_enhanced_scoring", {
                "time_cost": step6_time,
                "semantic_matching_enabled": bool(semantic_scores_map),
                "semantic_scores": semantic_scores_map,
                "processed_count": len(processed_evaluations),
                "score_details": [
                    {
                        "aic": e.get("aic"),
                        "skillid": e.get("skillid"),
                        "original_llm_score": e.get("original_llm_score"),
                        "enhanced_weighted_score": e.get("enhanced_weighted_score"),
                        "scoring_details": e.get("scoring_details")
                    }
                    for e in processed_evaluations
                ]
            })

            # 步骤7: 排序并取前k个
            t7 = time.time()
            processed_evaluations.sort(key=lambda x: x["enhanced_weighted_score"], reverse=True)
            final_evaluations = processed_evaluations[:k]
            step7_time = time.time() - t7
            print(f"🏁 [Step7] 排序完成，取前 {k} 项，用时 {step7_time:.3f}s")
            
            self._log_step("step7_ranking", {
                "time_cost": step7_time,
                "before_ranking": len(processed_evaluations),
                "after_ranking": len(final_evaluations),
                "final_rankings": [
                    {
                        "rank": i+1,
                        "aic": e.get("aic"),
                        "skillid": e.get("skillid"),
                        "score": e.get("enhanced_weighted_score")
                    }
                    for i, e in enumerate(final_evaluations)
                ]
            })

            # 步骤8: 构造结果
            t8 = time.time()
            skills_ranking = []
            for rank, eval_item in enumerate(final_evaluations, 1):
                skill_description = eval_item.get("full_skill_info", {}).get("description", "")
                parent_agent = eval_item.get("parent_agent_info") or next(
                    (agent for agent in self.agents if agent.get("aic") == eval_item["aic"]), {}
                )
                agent_url = self._extract_agent_url(parent_agent) if parent_agent else ""

                skills_ranking.append({
                    "aic": eval_item["aic"],
                    "description": skill_description,
                    "url": agent_url,
                    "skillid": eval_item["skillid"],
                    "ranking": rank,
                    "memo": f"LLM得分: {eval_item['original_llm_score']:.3f}, 增强得分: {eval_item['enhanced_weighted_score']:.3f}",
                    "acs": parent_agent
                })
            step8_time = time.time() - t8
            print(f"📦 [Step8] 构造最终返回结构完成，用时 {step8_time:.3f}s")
            
            self._log_step("step8_build_result", {
                "time_cost": step8_time,
                "final_count": len(skills_ranking)
            })

            # 汇总结果
            result = {
                "skills": skills_ranking,
                "reasoning": llm_reasoning, 
                "scoring_method": "enhanced_skill_based_discovery_optimized", 
                "optimization_stats": {
                    "original_skill_count": len(all_skills),
                    "candidates_sent_to_llm": len(candidate_skills),
                    "llm_returned_count": len(llm_ranked_skills),
                    "llm_filtered_count": len(filtered_llm_skills),
                    "llm_excluded_count": excluded_count,
                    "llm_score_threshold": llm_score_threshold,
                    "final_returned_count": len(final_evaluations),
                    "skill_reduction_ratio": 1 - (len(candidate_skills) / len(all_skills)) if all_skills else 0,
                    "prefilter_enabled": self.optimization_config["prefilter_enabled"],
                },
                "scoring_config": self.scoring_config
            }

            total_time = time.time() - total_start
            print(f"✅ [DONE] 技能发现完成，用时 {total_time:.3f}s，总计 {len(skills_ranking)} 个最佳技能\n")
            
            self.current_log_data["output"] = result
            self._save_log()
            
            return result

        except json.JSONDecodeError as e:
            print(f"❌ 解析LLM响应失败: {e}")
            print(f"原始响应前500字符: {response[:500]}...")
            error_result = {"error": "LLM响应格式错误", "raw_response": response[:500]}
            self.current_log_data["error"] = f"JSON解析错误: {str(e)}"
            self.current_log_data["output"] = error_result
            self._save_log()
            return error_result
        except Exception as e:
            print(f"❌ 技能发现过程失败: {e}")
            import traceback
            traceback.print_exc()
            error_result = {"error": str(e)}
            self.current_log_data["error"] = str(e)
            self.current_log_data["error_traceback"] = traceback.format_exc()
            self.current_log_data["output"] = error_result
            self._save_log()
            return {"error": str(e)}
        

    def discover_skills(self, task_description: str,
                        task_requirements: Optional[Dict[str, Any]] = None,
                        k: int = 5) -> Dict[str, Any]:
        """同步版本 - 基于技能的增强发现"""
        return asyncio.run(self.discover_skills_enhanced(task_description, task_requirements, k))

    
    def update_scoring_config(self, **kwargs):
        """更新评分配置"""
        self.scoring_config.update(kwargs)
        print(f"评分配置已更新: {self.scoring_config}")
    
    def update_optimization_config(self, **kwargs):
        """更新优化配置"""
        self.optimization_config.update(kwargs)
        
        print(f"优化配置已更新: {self.optimization_config}")
