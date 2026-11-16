import { useEffect, useRef } from 'react'
import {
  AreaSeries,
  BaselineSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { EquityPoint, FundingPoint } from '../api'

const UP = '#0ecb81'
const DOWN = '#f6465d'
const ACCENT = '#fcd535'
const GRID = 'rgba(43, 49, 57, 0.55)'
const TEXT = '#848e9c'

function baseOptions(height: number) {
  return {
    height,
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: TEXT,
      fontFamily:
        'ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
      fontSize: 10,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: GRID },
      horzLines: { color: GRID },
    },
    localization: {
      locale: 'zh-CN',
    },
    rightPriceScale: {
      borderColor: 'rgba(43, 49, 57, 0.9)',
      scaleMargins: { top: 0.18, bottom: 0.08 },
    },
    timeScale: {
      borderColor: 'rgba(43, 49, 57, 0.9)',
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 2,
      barSpacing: 6,
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: 'rgba(234, 236, 239, 0.25)', labelBackgroundColor: '#2b3139' },
      horzLine: { color: 'rgba(234, 236, 239, 0.25)', labelBackgroundColor: '#2b3139' },
    },
    handleScale: { axisPressedMouseMove: true },
  }
}

function fitWithPad(chart: IChartApi, count: number) {
  if (count <= 0) return
  chart.timeScale().setVisibleLogicalRange({ from: -6, to: count + 6 })
}

function useChartFactory(height: number) {
  const holder = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    const element = holder.current
    if (!element) return
    const chart = createChart(element, { ...baseOptions(height), width: element.clientWidth })
    chartRef.current = chart
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width) chart.applyOptions({ width })
    })
    observer.observe(element)
    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [height])

  return { holder, chartRef }
}

export function PriceChart({
  candles,
  height = 380,
  markers,
}: {
  candles: Array<[number, number, number, number, number, number]>
  height?: number
  markers?: Array<{ time: number; price: number; side: string }>
}) {
  const { holder, chartRef } = useChartFactory(height)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceLineVisible: true,
      priceLineColor: 'rgba(252, 213, 53, 0.5)',
      priceLineStyle: 2,
    })
    seriesRef.current = series
    markersRef.current = createSeriesMarkers(series, [])
    return () => {
      seriesRef.current = null
      markersRef.current = null
    }
  }, [chartRef])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    if (!series || !chart) return
    if (!candles.length) {
      series.setData([])
      return
    }
    series.setData(
      candles.map(([time, open, high, low, close]) => ({
        time: time as UTCTimestamp,
        open,
        high,
        low,
        close,
      })),
    )
    if (markers?.length) {
      const seen = new Set<string>()
      markersRef.current?.setMarkers(
        markers
          .map((marker) => ({
            time: marker.time as UTCTimestamp,
            position: marker.side === 'BUY' ? ('belowBar' as const) : ('aboveBar' as const),
            color: marker.side === 'BUY' ? UP : DOWN,
            shape: marker.side === 'BUY' ? ('circle' as const) : ('circle' as const),
            text: '',
            size: 0,
          }))
          .filter((marker) => {
            const key = `${marker.time}-${marker.position}`
            if (seen.has(key)) return false
            seen.add(key)
            return true
          }),
      )
    } else {
      markersRef.current?.setMarkers([])
    }
    fitWithPad(chart, candles.length)
  }, [candles, markers, chartRef])

  return <div ref={holder} className="w-full" />
}

export function EquityChart({
  equity,
  drawdown,
  height = 240,
  ddHeight = 96,
  baseline = true,
}: {
  equity: EquityPoint[]
  drawdown?: EquityPoint[]
  height?: number
  ddHeight?: number
  baseline?: boolean
}) {
  const { holder, chartRef } = useChartFactory(height)
  const seriesRef = useRef<ISeriesApi<'Area'> | ISeriesApi<'Baseline'> | null>(null)
  const ddHolder = useRef<HTMLDivElement | null>(null)
  const ddChartRef = useRef<IChartApi | null>(null)
  const ddSeriesRef = useRef<ISeriesApi<'Area'> | null>(null)

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (baseline) {
      const series = chart.addSeries(BaselineSeries, {
        baseValue: { type: 'price', price: equity[0]?.v ?? 10_000 },
        topLineColor: UP,
        topFillColor1: 'rgba(14, 203, 129, 0.24)',
        topFillColor2: 'rgba(14, 203, 129, 0.01)',
        bottomLineColor: DOWN,
        bottomFillColor1: 'rgba(246, 70, 93, 0.01)',
        bottomFillColor2: 'rgba(246, 70, 93, 0.22)',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      })
      seriesRef.current = series
    } else {
      const series = chart.addSeries(AreaSeries, {
        lineColor: ACCENT,
        topColor: 'rgba(252, 213, 53, 0.22)',
        bottomColor: 'rgba(252, 213, 53, 0.01)',
        lineWidth: 2,
        priceLineVisible: false,
      })
      seriesRef.current = series
    }
    return () => {
      seriesRef.current = null
    }
  }, [chartRef, baseline])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    if (!series || !chart) return
    series.setData(
      equity.map((point) => ({ time: point.t as UTCTimestamp, value: point.v })),
    )
    fitWithPad(chart, equity.length)
  }, [equity, chartRef])

  useEffect(() => {
    const element = ddHolder.current
    if (!element || !drawdown) return
    const chart = createChart(element, {
      ...baseOptions(ddHeight),
      width: element.clientWidth,
      rightPriceScale: {
        borderColor: 'rgba(43, 49, 57, 0.9)',
        scaleMargins: { top: 0.1, bottom: 0.02 },
      },
      timeScale: {
        borderColor: 'rgba(43, 49, 57, 0.9)',
        timeVisible: true,
        secondsVisible: false,
        visible: false,
        rightOffset: 2,
        barSpacing: 6,
      },
    })
    const series = chart.addSeries(AreaSeries, {
      lineColor: DOWN,
      topColor: 'rgba(246, 70, 93, 0.01)',
      bottomColor: 'rgba(246, 70, 93, 0.28)',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    series.setData(drawdown.map((point) => ({ time: point.t as UTCTimestamp, value: point.v })))
    fitWithPad(chart, drawdown.length)
    ddChartRef.current = chart
    ddSeriesRef.current = series
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width) chart.applyOptions({ width })
    })
    observer.observe(element)
    return () => {
      observer.disconnect()
      ddChartRef.current = null
      ddSeriesRef.current = null
      chart.remove()
    }
  }, [drawdown, ddHeight])

  return (
    <div>
      <div ref={holder} className="w-full" />
      {drawdown ? (
        <div ref={ddHolder} className="mt-1 w-full border-t border-line-soft pt-1" />
      ) : null}
    </div>
  )
}

export function CumulativeChart({
  points,
  height = 260,
}: {
  points: EquityPoint[]
  height?: number
}) {
  const { holder, chartRef } = useChartFactory(height)
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null)

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    seriesRef.current = chart.addSeries(AreaSeries, {
      lineColor: ACCENT,
      topColor: 'rgba(252, 213, 53, 0.22)',
      bottomColor: 'rgba(252, 213, 53, 0.01)',
      lineWidth: 2,
      priceLineVisible: true,
      priceLineColor: 'rgba(252, 213, 53, 0.45)',
    })
    return () => {
      seriesRef.current = null
    }
  }, [chartRef])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    if (!series || !chart) return
    series.setData(points.map((point) => ({ time: point.t as UTCTimestamp, value: point.v })))
    fitWithPad(chart, points.length)
  }, [points, chartRef])

  return <div ref={holder} className="w-full" />
}

export function FundingChart({
  points,
  height = 200,
}: {
  points: FundingPoint[]
  height?: number
}) {
  const { holder, chartRef } = useChartFactory(height)
  const seriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    seriesRef.current = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'price', precision: 4, minMove: 0.0001 },
      priceLineVisible: false,
      base: 0,
    })
    return () => {
      seriesRef.current = null
    }
  }, [chartRef])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    if (!series || !chart) return
    series.setData(
      points.map((point) => ({
        time: point.time as UTCTimestamp,
        value: point.rate,
        color: point.rate >= 0 ? 'rgba(14, 203, 129, 0.72)' : 'rgba(246, 70, 93, 0.72)',
      })),
    )
    fitWithPad(chart, points.length)
  }, [points, chartRef])

  return <div ref={holder} className="w-full" />
}
