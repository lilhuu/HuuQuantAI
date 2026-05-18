<script setup>
import { onMounted, onUnmounted, ref, watch } from "vue";
import { Chart, registerables } from "chart.js";

Chart.register(...registerables);

const props = defineProps({
  equityCurve: { type: Array, default: () => [] },
  drawdownCurve: { type: Array, default: () => [] },
  height: { type: Number, default: 280 },
});

const canvasRef = ref(null);
let chartInstance = null;

function buildChartData() {
  const equity = props.equityCurve || [];
  const drawdown = props.drawdownCurve || [];
  const labels = (equity.length ? equity : drawdown).map((point) => point.timestamp || "");

  return {
    labels,
    datasets: [
      {
        label: "权益曲线",
        data: equity.map((point) => point.equity ?? 0),
        borderColor: "#13d6d6",
        backgroundColor: "rgba(19, 214, 214, 0.08)",
        fill: true,
        tension: 0.28,
        pointRadius: 0,
        borderWidth: 2,
        yAxisID: "y",
      },
      {
        label: "回撤",
        data: drawdown.map((point) => (point.drawdown ?? 0) * 100),
        borderColor: "#ff6b6b",
        backgroundColor: "rgba(255, 107, 107, 0.08)",
        fill: true,
        tension: 0.28,
        pointRadius: 0,
        borderWidth: 1.5,
        yAxisID: "y1",
      },
    ],
  };
}

function buildChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      intersect: false,
      mode: "index",
    },
    plugins: {
      legend: {
        display: true,
        position: "top",
        labels: {
          color: "#f1f5ff",
          usePointStyle: true,
          boxWidth: 8,
        },
      },
      tooltip: {
        callbacks: {
          label(context) {
            const value = Number(context.raw || 0);
            if (context.datasetIndex === 1) {
              return `回撤: ${value.toFixed(2)}%`;
            }
            return `权益: ${value.toLocaleString("zh-CN", { minimumFractionDigits: 2 })} USDT`;
          },
        },
      },
    },
    scales: {
      x: {
        ticks: { color: "#9db0c6", maxTicksLimit: 8, font: { size: 10 } },
        grid: { color: "rgba(154, 182, 214, 0.08)" },
      },
      y: {
        type: "linear",
        position: "left",
        ticks: {
          color: "#9db0c6",
          callback(value) {
            return Number(value).toLocaleString("zh-CN", { notation: "compact" });
          },
        },
        grid: { color: "rgba(154, 182, 214, 0.10)" },
      },
      y1: {
        type: "linear",
        position: "right",
        grid: { drawOnChartArea: false },
        ticks: {
          color: "#9db0c6",
          callback(value) {
            return `${Number(value).toFixed(1)}%`;
          },
        },
      },
    },
  };
}

function renderChart() {
  if (!canvasRef.value) {
    return;
  }

  if (chartInstance) {
    chartInstance.destroy();
    chartInstance = null;
  }

  const hasData = Boolean(props.equityCurve?.length || props.drawdownCurve?.length);
  if (!hasData) {
    return;
  }

  chartInstance = new Chart(canvasRef.value, {
    type: "line",
    data: buildChartData(),
    options: buildChartOptions(),
  });
}

watch(() => [props.equityCurve, props.drawdownCurve], renderChart, { deep: true });

onMounted(renderChart);

onUnmounted(() => {
  if (chartInstance) {
    chartInstance.destroy();
    chartInstance = null;
  }
});
</script>

<template>
  <div class="chart-wrap" :style="{ height: `${height}px` }">
    <canvas ref="canvasRef"></canvas>
    <div v-if="!equityCurve.length && !drawdownCurve.length" class="chart-empty">
      暂无回测数据
    </div>
  </div>
</template>

<style scoped>
.chart-wrap {
  position: relative;
  width: 100%;
  margin-top: 18px;
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
