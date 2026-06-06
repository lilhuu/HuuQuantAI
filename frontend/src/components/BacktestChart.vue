<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { LineSeries, createChart } from "lightweight-charts";

const props = defineProps({
  equityCurve: { type: Array, default: () => [] },
  drawdownCurve: { type: Array, default: () => [] },
  height: { type: Number, default: 280 },
});

const chartEl = ref(null);
let chart = null;
let equitySeries = null;
let drawdownSeries = null;
let resizeObserver = null;

const hasData = computed(() => Boolean(props.equityCurve?.length || props.drawdownCurve?.length));

const equityRows = computed(() =>
  normalizeSeries(props.equityCurve, "equity").filter((item) => Number.isFinite(item.value)),
);

const drawdownRows = computed(() =>
  normalizeSeries(props.drawdownCurve, "drawdown")
    .map((item) => ({ ...item, value: item.value * 100 }))
    .filter((item) => Number.isFinite(item.value)),
);

function normalizeSeries(items = [], field) {
  return (items || [])
    .map((point, index) => ({
      time: toChartTime(point.timestamp || point.time || point.date, index),
      value: Number(point[field] ?? 0),
    }))
    .filter((item) => item.time)
    .sort((left, right) => Number(left.time) - Number(right.time));
}

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

function formatChartTime(time) {
  const date = new Date(Number(time) * 1000);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${month}-${day} ${hours}:${minutes}`;
}

function renderChart() {
  if (!chartEl.value) return;
  if (!chart) {
    chart = createChart(chartEl.value, {
      height: props.height,
      layout: { background: { color: "transparent" }, textColor: "#9db0c6" },
      grid: {
        vertLines: { color: "rgba(154, 176, 198, 0.08)" },
        horzLines: { color: "rgba(154, 176, 198, 0.08)" },
      },
      rightPriceScale: { borderColor: "rgba(154, 176, 198, 0.16)" },
      leftPriceScale: { visible: true, borderColor: "rgba(154, 176, 198, 0.16)" },
      timeScale: {
        borderColor: "rgba(154, 176, 198, 0.28)",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: formatChartTime,
      },
      localization: {
        timeFormatter: formatChartTime,
        priceFormatter: (price) => Number(price || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 }),
      },
      crosshair: { mode: 1 },
    });
    equitySeries = chart.addSeries(LineSeries, {
      color: "#13d6d6",
      lineWidth: 2,
      priceScaleId: "right",
      title: "权益 USDT",
    });
    drawdownSeries = chart.addSeries(LineSeries, {
      color: "#ff6b6b",
      lineWidth: 2,
      priceScaleId: "left",
      title: "回撤 %",
    });
    resizeObserver = new ResizeObserver(() => {
      if (chart && chartEl.value) {
        chart.applyOptions({ width: chartEl.value.clientWidth, height: props.height });
      }
    });
    resizeObserver.observe(chartEl.value);
  }

  equitySeries.setData(equityRows.value);
  drawdownSeries.setData(drawdownRows.value);
  if (hasData.value) {
    chart.timeScale().fitContent();
  }
}

watch(() => [props.equityCurve, props.drawdownCurve, props.height], () => nextTick(renderChart), { deep: true });

onMounted(() => nextTick(renderChart));

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect();
  if (chart) chart.remove();
  resizeObserver = null;
  chart = null;
  equitySeries = null;
  drawdownSeries = null;
});
</script>

<template>
  <div class="chart-wrap" :style="{ height: `${height}px` }">
    <div ref="chartEl" class="backtest-chart"></div>
    <div v-if="!hasData" class="chart-empty">暂无回测数据</div>
  </div>
</template>

<style scoped>
.chart-wrap {
  position: relative;
  width: 100%;
  margin-top: 18px;
}

.backtest-chart {
  width: 100%;
  height: 100%;
}

.chart-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #9db0c6;
  font-size: 14px;
}
</style>
