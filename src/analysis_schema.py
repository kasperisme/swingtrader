from pydantic import BaseModel, Field
from typing import List, Optional, Union, Literal
from datetime import date


class EntryStrategy(BaseModel):
    entry_level: float = Field(description="Entry price level")
    entry_type: Literal["breakout", "anticipatory", "trend-following"] = Field(
        description="Type of entry strategy"
    )
    entry_comment: str = Field(description="Comment explaining the entry strategy")


class StopLoss(BaseModel):
    level: float = Field(description="Stop loss price level")
    method: Literal["percent_below_entry", "structure_based"] = Field(
        description="Method used for stop loss"
    )
    comment: str = Field(description="Comment explaining the stop loss placement")


class TakeProfit(BaseModel):
    initial_target: float = Field(description="Initial profit target price")
    scaling_plan: str = Field(description="Plan for scaling out of the position")
    comment: str = Field(description="Comment explaining the profit taking strategy")


class TradeProposal(BaseModel):
    entry_strategy: EntryStrategy = Field(description="Entry strategy details")
    stop_loss: StopLoss = Field(description="Stop loss details")
    take_profit: TakeProfit = Field(description="Take profit details")
    risk_reward_ratio: float = Field(description="Risk to reward ratio")
    proposal_confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence level of the trade proposal"
    )


class PrimaryPattern(BaseModel):
    name: str = Field(description="Name of the primary pattern identified")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence level of the pattern identification"
    )
    depth_percent: Optional[float] = Field(
        None, description="Depth of the pattern as a percentage"
    )
    duration_weeks: Optional[float] = Field(
        None, description="Duration of the pattern in weeks"
    )
    volume_characteristics: Optional[str] = Field(
        None, description="Volume characteristics of the pattern"
    )
    rs_rating: Optional[float] = Field(None, description="Relative strength rating")


class SecondaryCandidate(BaseModel):
    name: str = Field(description="Name of the secondary pattern candidate")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence level of the secondary pattern"
    )


class PriceTrend(BaseModel):
    trend_direction: Literal["up", "down", "sideways"] = Field(
        description="Overall price trend direction"
    )
    ma_alignment: Optional[str] = Field(None, description="Moving average alignment")
    support_levels: Optional[List[float]] = Field(
        None, description="Key support levels"
    )
    resistance_levels: Optional[List[float]] = Field(
        None, description="Key resistance levels"
    )


class VolumeTrend(BaseModel):
    volume_trend: Optional[str] = Field(None, description="Volume trend analysis")
    relative_volume: Optional[float] = Field(
        None, description="Relative volume compared to average"
    )
    breakout_volume: Optional[float] = Field(
        None, description="Volume on breakout days"
    )


class FundamentalsSummary(BaseModel):
    eps_growth: Optional[float] = Field(None, description="EPS growth rate")
    revenue_growth: Optional[float] = Field(None, description="Revenue growth rate")
    earnings_quality: Optional[str] = Field(None, description="Quality of earnings")
    estimate_beats: Optional[int] = Field(None, description="Number of estimate beats")


class MarketContext(BaseModel):
    market_condition: Optional[str] = Field(
        None, description="Overall market condition"
    )
    sector_performance: Optional[str] = Field(
        None, description="Sector performance analysis"
    )
    relative_strength: Optional[float] = Field(
        None, description="Relative strength vs market"
    )


class IBDAnalysis(BaseModel):
    ticker: str = Field(description="Stock ticker symbol")
    as_of_date: date = Field(description="Analysis date")
    timeframe: Literal["daily"] = Field(
        default="daily", description="Analysis timeframe"
    )
    primary_pattern: PrimaryPattern = Field(description="Primary pattern identified")
    secondary_candidates: List[SecondaryCandidate] = Field(
        description="Secondary pattern candidates"
    )
    price_trend: PriceTrend = Field(description="Price trend analysis")
    volume_trend: VolumeTrend = Field(description="Volume trend analysis")
    fundamentals_summary: FundamentalsSummary = Field(
        description="Fundamentals summary"
    )
    market_context: MarketContext = Field(description="Market context analysis")
    decision_commentary: str = Field(
        description="Decision commentary explaining the analysis"
    )
    trade_proposal: Optional[TradeProposal] = Field(
        None, description="Trade proposal if warranted"
    )
    missing_data: List[str] = Field(description="List of missing data points")

    class Config:
        json_schema_extra = {
            "example": {
                "ticker": "EXMP",
                "as_of_date": "2025-09-02",
                "timeframe": "daily",
                "primary_pattern": {
                    "name": "CupWithHandle",
                    "confidence": 0.78,
                    "depth_percent": 15.2,
                    "duration_weeks": 8.5,
                    "volume_characteristics": "Declining volume on pullback, expanding on breakout",
                    "rs_rating": 85.0,
                },
                "secondary_candidates": [{"name": "VCP", "confidence": 0.65}],
                "price_trend": {
                    "trend_direction": "up",
                    "ma_alignment": "Bullish - price above all MAs",
                    "support_levels": [45.20, 42.80],
                    "resistance_levels": [52.10, 55.30],
                },
                "volume_trend": {
                    "volume_trend": "Increasing on up days",
                    "relative_volume": 1.4,
                    "breakout_volume": 2.1,
                },
                "fundamentals_summary": {
                    "eps_growth": 25.3,
                    "revenue_growth": 18.7,
                    "earnings_quality": "High - consistent beats",
                    "estimate_beats": 3,
                },
                "market_context": {
                    "market_condition": "Constructive",
                    "sector_performance": "Outperforming",
                    "relative_strength": 87.5,
                },
                "decision_commentary": "Strong CAN SLIM fundamentals + constructive handle and breakout volume. Trade setup justified.",
                "trade_proposal": {
                    "entry_strategy": {
                        "entry_level": 51.40,
                        "entry_type": "breakout",
                        "entry_comment": "Entry slightly above handle high with confirmation volume.",
                    },
                    "stop_loss": {
                        "level": 47.70,
                        "method": "structure_based",
                        "comment": "Below handle low and 50d line.",
                    },
                    "take_profit": {
                        "initial_target": 61.70,
                        "scaling_plan": "Take partial at +20%, trail remainder with 50d MA.",
                        "comment": "Target aligns with O'Neil's 20–25% profit-taking rule.",
                    },
                    "risk_reward_ratio": 2.6,
                    "proposal_confidence": 0.74,
                },
                "missing_data": [],
            }
        }
