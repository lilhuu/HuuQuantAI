<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { CandlestickSeries, HistogramSeries, LineSeries, createChart } from "lightweight-charts";

const props = defineProps({
  candles: { type: Array, default: () => [] },
  height: { type: Number, default: 360 },
});

const chartEl = ref(null);
let chart = null;
let candleSeries = null;
let volumeSeries = null;
let ma7Series = null;
let ma25Series = null;
let ma99Series = null;
let resizeObserver = null;

const normalizedCandles = computed(() =>
  (props.candles || [])
    .map((item, index) => ({
      time: toChartTime(item.start_time || item.timestamp || item.time, index),
      open: Number(item.open || item.close || 0),
      high: Number(item.high || item.close || 0),
      low: Number(item.low || item.close || 0),
      close: Number(item.close || 0),
      volume: Number(item.volume || 0),
    }))
    .filter((item) => item.time && item.open > 0 && item.high > 0 && item.low > 0 && item.close > 0)
    .sort((a, b) => Number(a.time) - Number(b.time)),
);

function toChartTime(value, fallbackIndex) {
  if (typeof value === "number") {
    return value > 10_000_000_000 ? Math.floor(value / 1000) : Math.floor(value);
  }
  if (value) {
    const parsed = Date.parse(String(value));
    if (!Number.isNaN(parsed)) {
      return Math.floor(parsed / 1000);
    }
  }
  return Math.floor(Date.now() / 1000) + fallbackIndex;
}

function chartTimeToDate(time) {
  if (typeof time === "number") {
    return new Date(time * 1000);
  }
  if (time && typeof time === "object" && "year" in time) {
    return new Date(Date.UTC(Number(time.year), Number(time.month || 1) - 1, Number(time.day || 1)));
  }
  return null;
}

function formatChartTime(time) {
  const date = chartTimeToDate(time);
  if (!date || Number.isNaN(date.getTime())) {
    return "";
  }
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${month}-${day} ${hours}:${minutes}`;
}

function movingAverage(rows, period) {
  const result = [];
  for (let index = period - 1; index < rows.length; index += 1) {
    const slice = rows.slice(index - period + 1, index + 1);
    const average = slice.reduce((sum, item) => sum + item.close, 0) / period;
    result.push({ time: rows[index].time, value: average });
  }
  return result;
}

function renderChart() {
  if (!chartEl.value) return;
  if (!chart) {
    chart = createChart(chartEl.value, {
      height: props.height,
      layout: { background: { color: "#111318" }, textColor: "#9db0c6" },
      grid: {
        vertLines: { color: "rgba(154, 176, 198, 0.08)" },
        horzLines: { color: "rgba(154, 176, 198, 0.08)" },
      },
      rightPriceScale: { borderColor: "rgba(154, 176, 198, 0.16)" },
      timeScale: {
        borderColor: "rgba(154, 176, 198, 0.28)",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: formatChartTime,
      },
      localization: {
        timeFormatter: formatChartTime,
      },
      crosshair: { mode: 1 },
    });
    candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#24d18f",
      downColor: "#ff6b6b",
      borderUpColor: "#24d18f",
      borderDownColor: "#ff6b6b",
      wickUpColor: "#24d18f",
      wickDownColor: "#ff6b6b",
    });
    volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      color: "rgba(37, 208, 207, 0.35)",
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    ma7Series = chart.addSeries(LineSeries, { color: "#f5d46d", lineWidth: 1 });
    ma25Series = chart.addSeries(LineSeries, { color: "#5aa8ff", lineWidth: 1 });
    ma99Series = chart.addSeries(LineSeries, { color: "#b178ff", lineWidth: 1 });
    resizeObserver = new ResizeObserver(() => {
      if (chart && chartEl.value) {
        chart.applyOptions({
          width: chartEl.value.clientWidth,
          height: props.height,
        });
      }
    });
    resizeObserver.observe(chartEl.value);
  }

  const rows = normalizedCandles.value;
  if (!rows.length) return;
  candleSeries.setData(rows.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
  volumeSeries.setData(
    rows.map((item) => ({
      time: item.time,
      value: item.volume,
      color: item.close >= item.open ? "rgba(36, 209, 143, 0.36)" : "rgba(255, 107, 107, 0.36)",
    })),
  );
  ma7Series.setData(movingAverage(rows, 7));
  ma25Series.setData(movingAverage(rows, 25));
  ma99Series.setData(movingAverage(rows, 99));
  chart.timeScale().fitContent();
}

watch(normalizedCandles, () => nextTick(renderChart), { deep: true });

onMounted(() => nextTick(renderChart));

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect();
  if (chart) chart.remove();
  chart = null;
});
</script>

<template>
  <div class="chart-wrap" :style="{ height: `${height}px` }">
    <div ref="chartEl" class="kline-chart"></div>
    <div v-if="!normalizedCandles.length" class="chart-empty">暂无 K 线数据</div>
  </div>
</template>

<style scoped>
.chart-wrap {
  position: relative;
  width: 100%;
}

.kline-chart {
  width: 100%;
  height: 100%;
}

.chart-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #9db0c6;
}
</style>
