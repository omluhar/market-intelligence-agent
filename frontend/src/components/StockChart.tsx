"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

export interface OhlcvBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function toChartTime(value: string): Time {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value as Time;
  }
  const parsed = Date.parse(value);
  if (!Number.isNaN(parsed)) {
    return Math.floor(parsed / 1000) as UTCTimestamp;
  }
  return value as Time;
}

export default function StockChart({
  data,
  height = 280,
  timeVisible = false,
}: {
  data: OhlcvBar[];
  height?: number;
  timeVisible?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const dataRef = useRef(data);
  dataRef.current = data;

  useEffect(() => {
    const node = containerRef.current;
    if (!node) {
      return;
    }

    const chart = createChart(node, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#a3a3a3",
        fontFamily: "inherit",
      },
      grid: {
        vertLines: { color: "#262626" },
        horzLines: { color: "#262626" },
      },
      width: node.clientWidth,
      height,
      autoSize: false,
      timeScale: {
        borderColor: "#262626",
        timeVisible,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: "#262626",
      },
      crosshair: {
        vertLine: { color: "#525252" },
        horzLine: { color: "#525252" },
      },
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#34d399",
      downColor: "#f87171",
      borderVisible: false,
      wickUpColor: "#34d399",
      wickDownColor: "#f87171",
    });
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });

    const observer = new ResizeObserver(() => {
      if (!containerRef.current) {
        return;
      }
      chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    observer.observe(node);
    chartRef.current = chart;
    candlesRef.current = candles;
    volumeRef.current = volume;

    const current = dataRef.current;
    if (current.length) {
      candles.setData(
        current.map((bar) => ({
          time: toChartTime(bar.time),
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        }))
      );
      volume.setData(
        current.map((bar) => ({
          time: toChartTime(bar.time),
          value: bar.volume,
          color: bar.close >= bar.open ? "rgba(52, 211, 153, 0.35)" : "rgba(248, 113, 113, 0.35)",
        }))
      );
      chart.timeScale().fitContent();
    }

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candlesRef.current = null;
      volumeRef.current = null;
    };
  }, [height, timeVisible]);

  useEffect(() => {
    if (!candlesRef.current || !volumeRef.current || !chartRef.current) {
      return;
    }
    if (data.length === 0) {
      candlesRef.current.setData([]);
      volumeRef.current.setData([]);
      return;
    }
    candlesRef.current.setData(
      data.map((bar) => ({
        time: toChartTime(bar.time),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
    );
    volumeRef.current.setData(
      data.map((bar) => ({
        time: toChartTime(bar.time),
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(52, 211, 153, 0.35)" : "rgba(248, 113, 113, 0.35)",
      }))
    );
    chartRef.current.timeScale().fitContent();
  }, [data]);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-neutral-500 border border-neutral-800/80 rounded-lg bg-neutral-950/60"
        style={{ height }}
      >
        No historical bars available.
      </div>
    );
  }

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}
