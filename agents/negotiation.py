"""
多 Agent 协商机制
实现 Agent 之间的讨论、投票和共识达成
"""

from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from config.settings import settings


class ProposalStatus(str, Enum):
    """提案状态"""
    PENDING = "pending"       # 待讨论
    DISCUSSING = "discussing" # 讨论中
    VOTING = "voting"         # 投票中
    APPROVED = "approved"     # 已通过
    REJECTED = "rejected"     # 已拒绝
    REVISED = "revised"       # 已修订


@dataclass
class Proposal:
    """提案"""
    id: str
    proposer: str                    # 提案者
    content: str                     # 提案内容
    proposal_type: str               # 类型: task, strategy, correction
    status: ProposalStatus = ProposalStatus.PENDING
    votes: Dict[str, str] = field(default_factory=dict)  # agent_name -> vote
    discussions: List[Dict] = field(default_factory=list)
    revisions: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    consensus_reached: bool = False


@dataclass
class NegotiationRound:
    """协商轮次"""
    round_number: int
    proposals: List[Proposal]
    participants: List[str]
    current_topic: str
    consensus_threshold: float = 0.66  # 共识阈值 (2/3)
    max_rounds: int = 5
    completed: bool = False


class MultiAgentNegotiation:
    """
    多 Agent 协商系统
    支持讨论、投票、共识达成
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.model_name,
            anthropic_api_url=settings.model_base_url,
            anthropic_api_key=settings.model_api_key,
            temperature=0.5,
            max_tokens=2048
        )
        self.active_negotiations: Dict[str, NegotiationRound] = {}
        self.agents: Dict[str, Dict[str, Any]] = {}  # 注册参与的 agent

    def register_agent(
        self,
        name: str,
        role: str,
        expertise: List[str],
        priority: int = 1
    ):
        """注册 Agent"""
        self.agents[name] = {
            "name": name,
            "role": role,
            "expertise": expertise,
            "priority": priority,
            "joined_at": datetime.now().isoformat()
        }
        print(f"[Negotiation] 注册 Agent: {name} ({role})")

    async def start_negotiation(
        self,
        topic: str,
        initial_proposals: List[Dict[str, Any]],
        participants: List[str] = None,
        negotiation_id: str = None
    ) -> str:
        """
        启动协商过程
        """
        negotiation_id = negotiation_id or f"neg_{datetime.now().timestamp()}"

        # 创建提案对象
        proposals = []
        for i, prop_data in enumerate(initial_proposals):
            proposal = Proposal(
                id=f"{negotiation_id}_prop_{i}",
                proposer=prop_data.get("proposer", "unknown"),
                content=prop_data.get("content", ""),
                proposal_type=prop_data.get("type", "general")
            )
            proposals.append(proposal)

        # 确定参与者
        participants = participants or list(self.agents.keys())

        negotiation = NegotiationRound(
            round_number=1,
            proposals=proposals,
            participants=participants,
            current_topic=topic
        )

        self.active_negotiations[negotiation_id] = negotiation

        print(f"[Negotiation] 启动协商: {negotiation_id}")
        print(f"  主题: {topic}")
        print(f"  提案数: {len(proposals)}")
        print(f"  参与者: {participants}")

        # 开始协商循环
        await self._run_negotiation(negotiation_id)

        return negotiation_id

    async def _run_negotiation(self, negotiation_id: str):
        """运行协商过程"""
        negotiation = self.active_negotiations[negotiation_id]

        while negotiation.round_number <= negotiation.max_rounds:
            print(f"\n[Negotiation] 第 {negotiation.round_number} 轮讨论")

            # 1. 每个 agent 发表意见
            for agent_name in negotiation.participants:
                opinion = await self._generate_opinion(
                    agent_name,
                    negotiation.current_topic,
                    negotiation.proposals
                )

                # 将意见添加到相关提案的讨论中
                for proposal in negotiation.proposals:
                    proposal.discussions.append({
                        "agent": agent_name,
                        "round": negotiation.round_number,
                        "opinion": opinion,
                        "timestamp": datetime.now().isoformat()
                    })

            # 2. 检查是否达成共识
            consensus = self._check_consensus(negotiation)

            if consensus["reached"]:
                negotiation.completed = True
                print(f"[Negotiation] 达成共识!")
                break

            # 3. 如未达成，进入下一轮或修订提案
            if negotiation.round_number < negotiation.max_rounds:
                # 修订提案
                await self._revise_proposals(negotiation)

            negotiation.round_number += 1

        # 协商结束，确定最终结果
        result = self._finalize_negotiation(negotiation)
        negotiation.completed = True

        print(f"[Negotiation] 协商结束: {result['status']}")

    async def _generate_opinion(
        self,
        agent_name: str,
        topic: str,
        proposals: List[Proposal]
    ) -> str:
        """
        生成 Agent 的意见
        """
        agent_info = self.agents.get(agent_name, {})
        role = agent_info.get("role", "member")
        expertise = agent_info.get("expertise", [])

        # 构建 prompt
        proposals_text = "\n\n".join([
            f"提案 {i+1} (来自 {p.proposer}):\n{p.content}"
            for i, p in enumerate(proposals)
        ])

        prompt = f"""你是一位 {role}，专长于 {', '.join(expertise)}。

当前讨论主题: {topic}

待讨论的提案:
{proposals_text}

请从专业角度分析这些提案:
1. 评估每个提案的优缺点
2. 指出潜在问题或风险
3. 提出改进建议
4. 表明你的支持倾向

请用中文简明扼要地表达你的意见。"""

        messages = [
            SystemMessage(content=f"你是 {agent_name}，一位{role}。参与团队讨论并给出专业意见。"),
            HumanMessage(content=prompt)
        ]

        try:
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            print(f"[Negotiation] LLM 调用失败: {e}")
            return f"作为{role}，我倾向于支持当前提案，但需要注意实施细节。"

    def _check_consensus(self, negotiation: NegotiationRound) -> Dict[str, Any]:
        """
        检查是否达成共识
        """
        if not negotiation.proposals:
            return {"reached": False, "reason": "无提案"}

        # 统计每个提案的支持度
        for proposal in negotiation.proposals:
            if proposal.status != ProposalStatus.PENDING:
                continue

            # 分析讨论中的意见
            support_count = 0
            oppose_count = 0

            for discussion in proposal.discussions:
                opinion = discussion.get("opinion", "").lower()

                # 简单的情感分析
                positive_keywords = ["支持", "同意", "赞成", "好", "可行", "approve"]
                negative_keywords = ["反对", "不同意", "问题", "风险", "reject"]

                pos_score = sum(1 for kw in positive_keywords if kw in opinion)
                neg_score = sum(1 for kw in negative_keywords if kw in opinion)

                if pos_score > neg_score:
                    support_count += 1
                elif neg_score > pos_score:
                    oppose_count += 1

            total_participants = len(negotiation.participants)
            support_rate = support_count / total_participants if total_participants > 0 else 0

            if support_rate >= negotiation.consensus_threshold:
                proposal.status = ProposalStatus.APPROVED
                proposal.consensus_reached = True
                return {
                    "reached": True,
                    "winning_proposal": proposal,
                    "support_rate": support_rate
                }

        return {"reached": False, "reason": "未达共识阈值"}

    async def _revise_proposals(self, negotiation: NegotiationRound):
        """
        根据讨论修订提案
        """
        for proposal in negotiation.proposals:
            if proposal.status != ProposalStatus.PENDING:
                continue

            # 汇总讨论意见
            opinions = "\n".join([
                f"{d['agent']}: {d['opinion'][:100]}..."
                for d in proposal.discussions[-len(negotiation.participants):]
            ])

            prompt = f"""根据以下讨论意见，修订原提案。

原提案:
{proposal.content}

讨论意见:
{opinions}

请输出修订后的提案（保持简洁）。"""

            messages = [
                SystemMessage(content="你是一位提案修订专家。整合反馈意见，优化提案。"),
                HumanMessage(content=prompt)
            ]

            try:
                response = await self.llm.ainvoke(messages)
                revised_content = response.content

                if revised_content != proposal.content:
                    proposal.revisions.append(proposal.content)
                    proposal.content = revised_content
                    proposal.status = ProposalStatus.REVISED
                    print(f"[Negotiation] 提案 {proposal.id} 已修订")
            except Exception as e:
                print(f"[Negotiation] 提案修订失败: {e}")
                # 保持原提案不变

    def _finalize_negotiation(self, negotiation: NegotiationRound) -> Dict[str, Any]:
        """
        确定协商最终结果
        """
        # 找出得票最高的提案
        approved = [p for p in negotiation.proposals if p.status == ProposalStatus.APPROVED]

        if approved:
            best_proposal = approved[0]
            return {
                "status": "consensus_reached",
                "proposal": {
                    "id": best_proposal.id,
                    "content": best_proposal.content,
                    "proposer": best_proposal.proposer,
                    "rounds": negotiation.round_number
                }
            }

        # 未达成共识，返回讨论最充分的提案
        most_discussed = max(
            negotiation.proposals,
            key=lambda p: len(p.discussions)
        )

        return {
            "status": "no_consensus",
            "best_attempt": {
                "id": most_discussed.id,
                "content": most_discussed.content,
                "discussions_count": len(most_discussed.discussions)
            },
            "rounds": negotiation.round_number
        }

    async def quick_consult(
        self,
        question: str,
        agents: List[str],
        strategy: str = "vote"  # vote, debate, expert
    ) -> Dict[str, Any]:
        """
        快速咨询多个 Agent
        """
        if strategy == "vote":
            return await self._quick_vote(question, agents)
        elif strategy == "expert":
            return await self._expert_consult(question, agents)
        else:
            return await self._quick_debate(question, agents)

    async def _quick_vote(self, question: str, agents: List[str]) -> Dict[str, Any]:
        """快速投票"""
        votes = {}

        for agent_name in agents:
            vote = await self._single_vote(agent_name, question)
            votes[agent_name] = vote

        # 统计结果
        yes_count = sum(1 for v in votes.values() if v == "yes")
        no_count = sum(1 for v in votes.values() if v == "no")

        return {
            "strategy": "vote",
            "votes": votes,
            "result": "yes" if yes_count > no_count else "no",
            "confidence": max(yes_count, no_count) / len(agents) if agents else 0
        }

    async def _single_vote(self, agent_name: str, question: str) -> str:
        """单个 Agent 投票"""
        agent_info = self.agents.get(agent_name, {})
        role = agent_info.get("role", "member")

        prompt = f"""作为一位{role}，请对以下问题投票:

问题: {question}

请只回答: YES 或 NO"""

        messages = [
            SystemMessage(content=f"你是 {agent_name}"),
            HumanMessage(content=prompt)
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content.upper()
            return "yes" if "YES" in content else "no"
        except Exception as e:
            print(f"[Negotiation] 投票失败: {e}")
            return "no"  # 默认反对

    def get_negotiation_result(self, negotiation_id: str) -> Optional[Dict[str, Any]]:
        """获取协商结果"""
        negotiation = self.active_negotiations.get(negotiation_id)
        if not negotiation:
            return None

        return self._finalize_negotiation(negotiation)


# 全局实例
negotiation_system = MultiAgentNegotiation()
