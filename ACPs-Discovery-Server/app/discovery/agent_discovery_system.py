import json
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
import asyncio
import aiohttp
import os
from datetime import datetime
from pathlib import Path
from app.discovery.semantic_matcher import SemanticAgentMatcher
import jieba
import time
from datetime import datetime

class EnhancedAgentDiscoverySystem:
    """增强的智能体发现系统"""
    
    def __init__(self, api_key: str = None, api_endpoint: str = "https://api.deepseek.com/v1/chat/completions"):
        self.agents = []
        self.api_endpoint = api_endpoint
        self.api_key = api_key or os.getenv('DEEPSEEK_API_KEY')
        # 组件初始化
        script_path = Path(__file__).resolve()
        script_dir = script_path.parent

        # 加权评分配置
        self.scoring_config = {
            "llm_score_weight": 1.0,         # LLM评分权重
        }
        
        # 优化配置
        self.optimization_config = {
            "max_agents_to_llm": 20,         # 发送给LLM的最大数量
            "llm_return_multiplier": 2,      # LLM返回数量是k的几倍
            "prefilter_enabled": True,       # 是否启用预筛选
            "use_semantic_matching": True,  # 启用语义匹配
            "semantic_weight": 25,           # 语义匹配权重
            "keyword_weight": 10,            # 关键词匹配权重
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
        """调用DeepSeek API"""
        if not self.api_key:
            raise ValueError("API密钥未设置")
            
        print(" 正在调用DeepSeek API...")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8192,
            "temperature": 0.1,
            "stream": False
        }
        
        async with aiohttp.ClientSession() as session:
            print("  发送请求到DeepSeek API...")
            async with session.post(self.api_endpoint, headers=headers, json=payload) as response:
                print(f"  收到响应，状态码: {response.status}")
                
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"DeepSeek API错误 ({response.status}): {error_text}")
                
                result = await response.json()
                print("  DeepSeek API调用成功")
                
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    print(f"  收到响应长度: {len(content)} 字符")
                    return content
                else:
                    raise Exception("DeepSeek API响应格式异常")
    
    
    def _expand_agents_to_skills(self, agents: List[Dict]) -> List[Dict]:
        """把Agent展开为Skill候选列表，增强版本"""
        skill_candidates = []
        for agent in agents:
            agent_aic = agent.get("aic", "")
            # 使用新的URL提取方法
            agent_url = self._extract_agent_url(agent)
            agent_name = agent.get("name", "")
            agent_description = agent.get("description", "")
            # 新ACS结构中使用active字段
            agent_status = "active" if agent.get("active", False) else "inactive"
            provider_info = agent.get("provider", {})
            
            for skill in agent.get("skills", []):
                skill_candidate = {
                    # 基础信息
                    "aic": agent_aic,
                    "url": agent_url,
                    "skillid": skill.get("id", ""),
                    "skill_name": skill.get("name", ""),
                    "description": skill.get("description", ""),
                    
                    # 技能详细信息
                    "tags": skill.get("tags", []),
                    # 新ACS结构中使用inputModes和outputModes
                    "inputTypes": skill.get("inputModes", []),
                    "outputTypes": skill.get("outputModes", []),
                    "version": skill.get("version", ""),
                    "examples": skill.get("examples", []),
                    
                    # Agent信息（用于评分）
                    "agent_name": agent_name,
                    "agent_description": agent_description,
                    "agent_status": agent_status,
                    "provider": provider_info,
                    
                    # 完整Agent信息（用于后续处理）
                    "parent_agent": agent
                }
                skill_candidates.append(skill_candidate)
        
        return skill_candidates
    

    def _calculate_skill_prefilter_score(self, skill: Dict, task_keywords: set, task_requirements: Optional[Dict] = None) -> float:
        """计算技能级别的预筛选得分"""
        score = 0.0
        config = self.optimization_config
        
        # 1. 技能名称和描述匹配
        skill_name = skill.get("skill_name", "").lower()
        skill_description = skill.get("description", "").lower()
        skill_terms = set(skill_name.split() + skill_description.split())
        
        # 2. 技能标签匹配
        skill_tags = [tag.lower() for tag in skill.get("tags", [])]
        skill_terms.update(skill_tags)
        
        # 3. 输入输出类型匹配（适应新的字段名）
        input_types = [itype.lower() for itype in skill.get("inputTypes", [])]
        output_types = [otype.lower() for otype in skill.get("outputTypes", [])]
        skill_terms.update(input_types + output_types)
        
        # 关键词匹配得分
        keyword_matches = 0
        for keyword in task_keywords:
            if any(keyword in term for term in skill_terms):
                keyword_matches += 1
        score += keyword_matches * config["keyword_weight"]
        
        # 技能需求匹配
        if task_requirements:
            required_skills = [skill.lower() for skill in task_requirements.get('required_skills', [])]
            skill_matches = sum(1 for req_skill in required_skills 
                              if any(req_skill in term for term in skill_terms))
            score += skill_matches * 20  # 技能匹配权重更高
            
            # 数据类型匹配
            required_input_types = task_requirements.get('input_types', [])
            required_output_types = task_requirements.get('output_types', [])
            
            input_match = any(req_type in input_types for req_type in required_input_types)
            output_match = any(req_type in output_types for req_type in required_output_types)
            
            if input_match:
                score += 15
            if output_match:
                score += 15
        
        
        # 技能状态和版本加分
        if skill.get("version"):
            score += 2
        if skill.get("examples"):
            score += 3
            
        # Agent状态加分（使用新的状态判断）
        if skill.get("agent_status") == 'active':
            score += 5
            
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

    [你的任务]
    1.  评估以上每个技能与任务的匹配程度。
    2.  为每个技能给出一个0.0到1.0之间的分数（`score`），分数越高代表越匹配。
    3.  按分数从高到低排序。
    4.  **只返回**一个包含前 {llm_return_count} 个最匹配技能的JSON数组。

    [输出格式要求]
    - 严格按照以下JSON格式返回，不要包含任何其他文字、解释或代码块标记。
    - `reason`字段请用一句话简要说明推荐原因。

    [
    {{
        "aic": "aic-of-skill",
        "skillid": "skillid-of-skill",
        "score": 0.95,
        "reason": "该技能的核心功能与任务要求高度吻合。"
    }},
    {{
        "aic": "another-aic",
        "skillid": "another-skillid",
        "score": 0.87,
        "reason": "输入输出类型匹配，但功能覆盖不全。"
    }}
    ]
    """
        return prompt.strip()



    async def discover_skills_enhanced(self, task_description: str,
                                        task_requirements: Optional[Dict[str, Any]] = None,
                                        k: int = 5) -> Dict[str, Any]:
        """
        (优化版) 基于技能的智能体发现方法，采用精简Prompt和响应格式。
        """
        if not self.agents:
            return {"error": "没有可用的智能体"}

        try:
            total_start = time.time()
            print(f"\n🔍 [START] 启动基于技能的增强发现 (k={k}) @ {datetime.now().strftime('%H:%M:%S')}")

            # 步骤1: 展开所有技能、
            t1 = time.time()
            all_skills = self._expand_agents_to_skills(self.agents)
            print(f"📋 [Step1] 展开技能完成: {len(all_skills)} 个技能，用时 {time.time() - t1:.3f}s")

            # 步骤2: 技能级预筛选、
            t2 = time.time()
            candidate_skills = self._prefilter_skills(
                task_description,
                all_skills,
                task_requirements,
                self.optimization_config["max_agents_to_llm"]
            )
            print(f"⚙️ [Step2] 技能预筛选完成: {len(candidate_skills)} 个候选，用时 {time.time() - t2:.3f}s")

            # 步骤3: 构造简化的提示词
            t3 = time.time()
            prompt = self._create_skill_evaluation_prompt_simplified(
                task_description,
                task_requirements,
                k,
                candidate_skills
            )
            print(f"🧠 [Step3] 构造Prompt完成（长度={len(prompt)}），用时 {time.time() - t3:.3f}s")

            # 步骤4: 调用 LLM 
            t4 = time.time()
            print(f"📤 [Step4] 发送 {len(candidate_skills)} 个候选技能给LLM评估 ...")
            response = await self._call_llm_api(prompt)
            llm_cost = time.time() - t4
            print(f"📥 [Step4] LLM响应接收完成，用时 {llm_cost:.3f}s")

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
            
            # 直接解析为技能列表
            llm_ranked_skills = json.loads(response_text)
            print(f"📊 [Step5] 解析LLM响应成功: {len(llm_ranked_skills)} 项，用时 {time.time() - t5:.3f}s")

            # 步骤6: 应用增强加权得分
            t6 = time.time()
            semantic_scores_map = {}
            if self.optimization_config.get("use_semantic_matching", False) and self.semantic_matcher:
                try:
                    # 收集所有需要计算语义相似度的 AIC
                    all_aics = list(set([item.get("aic") for item in llm_ranked_skills]))
                    
                    print(f"🧠 批量计算 {len(all_aics)} 个智能体的语义相似度...")
                    # 一次性计算所有 AIC 的语义相似度
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
            for llm_item in llm_ranked_skills:
                aic = llm_item.get("aic")
                skillid = llm_item.get("skillid")
                llm_score = llm_item.get("score", 0.0)

                weighted_score, score_details = self._calculate_enhanced_weighted_score(aic, llm_score)

                # 🔥 优化点：直接从预计算的字典中获取语义分数
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
                
                # 匹配并附加完整的技能信息
                matching_skill = next(
                    (s for s in candidate_skills if s.get("aic") == aic and s.get("skillid") == skillid), None
                )
                if matching_skill:
                    eval_item["full_skill_info"] = matching_skill
                    eval_item["parent_agent_info"] = matching_skill.get("parent_agent")

                processed_evaluations.append(eval_item)
            
            print(f"📈 [Step6] 增强得分计算完成: {len(processed_evaluations)} 项，用时 {time.time() - t6:.3f}s")

            # 步骤7: 最终排序和截取
            t7 = time.time()
            # 根据增强后的总分进行最终排序
            processed_evaluations.sort(key=lambda x: x["enhanced_weighted_score"], reverse=True)
            final_evaluations = processed_evaluations[:k]
            print(f"🏁 [Step7] 排序完成，取前{k}项，用时 {time.time() - t7:.3f}s")

            # 步骤8: 构造结果 
            t8 = time.time()
            skills_ranking = []
            for rank, eval_item in enumerate(final_evaluations, 1):
                skill_description =eval_item.get("full_skill_info", {}).get("description", "")
                parent_agent = eval_item.get("parent_agent_info") or next((agent for agent in self.agents if agent.get("aic") == eval_item["aic"]), {})
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
            print(f"📦 [Step8] 构造最终返回结构完成，用时 {time.time() - t8:.3f}s")

            # 汇总结果
            result = {
                "skills": skills_ranking,
                "scoring_method": "enhanced_skill_based_discovery_optimized", 
                "optimization_stats": {
                    "original_skill_count": len(all_skills),
                    "candidates_sent_to_llm": len(candidate_skills),
                    "llm_returned_count": len(llm_ranked_skills),
                    "final_returned_count": len(final_evaluations),
                    "skill_reduction_ratio": 1 - (len(candidate_skills) / len(all_skills)) if all_skills else 0,
                    "prefilter_enabled": self.optimization_config["prefilter_enabled"],
                },
                "scoring_config": self.scoring_config
            }

            print(f"✅ [DONE] 技能发现完成，用时 {time.time() - total_start:.3f}s，总计 {len(skills_ranking)} 个最佳技能\n")
            return result

        except json.JSONDecodeError as e:
            print(f"❌ 解析LLM响应失败: {e}")
            print(f"原始响应前500字符: {response[:500]}...")
            return {"error": "LLM响应格式错误", "raw_response": response[:500]}
        except Exception as e:
            print(f"❌ 技能发现过程失败: {e}")
            import traceback
            traceback.print_exc() # 打印详细的错误堆栈
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
