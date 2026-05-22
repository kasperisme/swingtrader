"use client";

import {
  Activity,
  BarChart2,
  FileText,
  Gauge,
  Newspaper,
  TrendingUp,
} from "lucide-react";
import type { ScreeningsPrimaryTabDef } from "./screenings-types";

/** Tabs that apply to the whole filtered symbol list. */
export const SCREENINGS_MULTI_SYMBOL_TABS: ScreeningsPrimaryTabDef[] = [
  {
    id: "quotes",
    label: "Quotes",
    icon: <TrendingUp className="w-3.5 h-3.5" />,
  },
  {
    id: "sentiment",
    label: "Sentiment",
    icon: <Gauge className="w-3.5 h-3.5" />,
  },
];

/** Deep-dive tabs for a single selected ticker. */
export const SCREENINGS_DEEP_DIVE_TABS: ScreeningsPrimaryTabDef[] = [
  {
    id: "charts",
    label: "Charts",
    icon: <BarChart2 className="w-3.5 h-3.5" />,
  },
  {
    id: "articles",
    label: "Articles",
    icon: <FileText className="w-3.5 h-3.5" />,
  },
  {
    id: "news",
    label: "News Trend",
    icon: <Newspaper className="w-3.5 h-3.5" />,
  },
  {
    id: "relationship",
    label: "Relationships",
    icon: <Activity className="w-3.5 h-3.5" />,
  },
];
