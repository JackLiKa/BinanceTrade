import { useEffect, useState, type ReactNode } from 'react'
import { clamp, cx } from '../format'
import { DEFAULT_PARAMS, type GridParams } from '../params'
import { Field, Toggle } from './ui'

export function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
  suffix,
  placeholder,
  className,
}: {
  value: number | null
  onChange: (value: number | null) => void
  min?: number
  max?: number
  step?: number
  suffix?: string
  placeholder?: string
  className?: string
}) {
  const [draft, setDraft] = useState(value === null ? '' : String(value))
  useEffect(() => {
    setDraft(value === null ? '' : String(value))
  }, [value])

  const commit = (raw: string) => {
    const text = raw.trim()
    if (!text) {
      onChange(null)
      setDraft(value === null ? '' : String(value))
      return
    }
    const parsed = Number(text)
    if (!Number.isFinite(parsed)) {
      setDraft(value === null ? '' : String(value))
      return
    }
    const next = clamp(parsed, min ?? -Infinity, max ?? Infinity)
    onChange(next)
    setDraft(String(next))
  }

  return (
    <div className="relative">
      <input
        className={cx('input num pr-9', className)}
        inputMode="decimal"
        value={draft}
        step={step}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => commit(draft)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            commit(draft)
            ;(event.target as HTMLInputElement).blur()
          }
        }}
      />
      {suffix ? (
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 font-mono text-[10px] text-faint">
          {suffix}
        </span>
      ) : null}
    </div>
  )
}

export function ParamsForm({
  value,
  onChange,
  compact = false,
  footer,
}: {
  value: GridParams
  onChange: (next: GridParams) => void
  compact?: boolean
  footer?: ReactNode
}) {
  const set = <K extends keyof GridParams>(key: K, next: GridParams[K]) =>
    onChange({ ...value, [key]: next })

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Field label="本金" hint="USD 名义资金">
          <NumberInput value={value.capital} onChange={(next) => set('capital', next ?? 10_000)} min={100} max={10_000_000} suffix="$" />
        </Field>
        <Field label="杠杆" hint="总名义 / 本金">
          <NumberInput value={value.leverage} onChange={(next) => set('leverage', next ?? 0.5)} min={0.05} max={10} step={0.05} suffix="x" />
        </Field>
        <Field label="网格间距" hint="单格步长">
          <NumberInput value={value.spacing_bp} onChange={(next) => set('spacing_bp', next ?? 120)} min={1} max={10_000} suffix="bp" />
        </Field>
        <Field label="层数" hint="挂单总数">
          <NumberInput value={value.levels} onChange={(next) => set('levels', Math.round(next ?? 30))} min={1} max={500} />
        </Field>
        <Field label="止损回撤" hint="留空则关闭保护">
          <NumberInput
            value={value.stop_dd === null ? null : value.stop_dd * 100}
            onChange={(next) => set('stop_dd', next === null ? null : next / 100)}
            min={0}
            max={100}
            suffix="%"
            placeholder="关闭"
          />
        </Field>
        <Field label="重新锚定" hint="每隔多少根 K 线重设">
          <NumberInput
            value={value.reanchor_bars}
            onChange={(next) => set('reanchor_bars', next === null ? null : Math.round(next))}
            min={1}
            max={100_000}
            placeholder="不重设"
            suffix="根"
          />
        </Field>
      </div>

      {value.auto ? (
        <div className="rounded-lg border border-line-soft bg-[#12151a] p-3">
          <p className="mb-2 text-[10.5px] leading-relaxed text-muted">
            自动模式：ATR 决定网格间距，波动率目标决定杠杆上限，库存超过半格先平仓再重锚。
            间距/杠杆会随行情滚动调整，初始值仅作上限参考。
          </p>
          <div className="grid grid-cols-3 gap-3">
            <Field label="调参间隔" hint="K线根数">
              <NumberInput value={value.auto_interval ?? 240} onChange={(next) => set('auto_interval', Math.round(next ?? 240))} min={10} suffix="根" />
            </Field>
            <Field label="ATR 窗口" hint="K线根数">
              <NumberInput value={value.auto_atr_window ?? 120} onChange={(next) => set('auto_atr_window', Math.round(next ?? 120))} min={20} suffix="根" />
            </Field>
            <Field label="目标年化波动" hint="杠杆上限">
              <NumberInput value={(value.auto_target_vol ?? 0.25) * 100} onChange={(next) => set('auto_target_vol', (next ?? 25) / 100)} min={1} max={500} suffix="%" />
            </Field>
          </div>
        </div>
      ) : null}

      {!compact ? (
        <div className="grid grid-cols-3 gap-3">
          <Field label="挂单费率" hint="限价成交">
            <NumberInput
              value={Math.round(value.maker_fee * 10_000 * 100) / 100}
              onChange={(next) => set('maker_fee', (next ?? 2) / 10_000)}
              min={0}
              max={100}
              suffix="bp"
            />
          </Field>
          <Field label="吃单费率" hint="市价成交">
            <NumberInput
              value={Math.round(value.taker_fee * 10_000 * 100) / 100}
              onChange={(next) => set('taker_fee', (next ?? 5) / 10_000)}
              min={0}
              max={100}
              suffix="bp"
            />
          </Field>
          <Field label="滑点" hint="每笔成交">
            <NumberInput value={value.slip_bp} onChange={(next) => set('slip_bp', next ?? 0.2)} min={0} max={100} suffix="bp" />
          </Field>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line-soft bg-[#12151a] px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-3">
          <Toggle
            checked={value.intrabar}
            onChange={(next) => set('intrabar', next)}
            label="盘中撮合（乐观上界）"
          />
          <Toggle
            checked={!!value.auto}
            onChange={(next) => set('auto', next)}
            label="自动调参（ATR/波动率）"
          />
        </div>
        <button
          type="button"
          onClick={() => onChange({ ...DEFAULT_PARAMS })}
          className="text-[10.5px] text-faint transition-colors hover:text-muted"
        >
          恢复默认
        </button>
      </div>

      {footer}
    </div>
  )
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: Array<{ value: T; label: string }>
  value: T
  onChange: (next: T) => void
  className?: string
}) {
  return (
    <div className={cx('inline-flex overflow-hidden rounded-lg border border-line', className)}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cx(
            'px-3 py-1.5 text-[11.5px] transition-colors',
            option.value === value
              ? 'bg-elevated text-accent'
              : 'text-muted hover:bg-elevated/60 hover:text-ink',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
