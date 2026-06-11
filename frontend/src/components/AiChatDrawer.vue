<script setup>
import { computed, nextTick, ref, watch } from "vue";

import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useAiChatStore } from "../stores/aiChat";
import { useTradingStore } from "../stores/trading";

const aiChat = useAiChatStore();
const trading = useTradingStore();

const draft = ref("");
const symbol = ref(normalizeCryptoSymbol(trading.selectedCryptoSymbol || "BTC/USDT"));
const period = ref(trading.selectedCryptoPeriod || "1h");
const limit = ref(120);
const includeContext = ref(true);
const selectedModel = ref("deepseek-v4-flash");
const messageList = ref(null);

const periodOptions = ["1m", "5m", "15m", "1h", "4h", "1d"];
const modelOptions = [
  { label: "Flash", value: "deepseek-v4-flash" },
  { label: "Pro", value: "deepseek-v4-pro" },
];
const suggestedQuestions = [
  "这个项目怎么用？",
  "自动交易为什么没有下单？",
  "风控中心这些指标是什么意思？",
  "帮我解释当前模拟账户风险",
];

const pairOptions = computed(() => {
  const base = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", ...trading.cryptoWatchSymbols];
  return [...new Set(base.map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
});

const canSend = computed(() => draft.value.trim().length > 0 && !aiChat.loading);

function scrollToBottom() {
  nextTick(() => {
    if (messageList.value) {
      messageList.value.scrollTop = messageList.value.scrollHeight;
    }
  });
}

function useSuggestedQuestion(question) {
  draft.value = question;
}

async function send() {
  if (!canSend.value) {
    return;
  }
  const message = draft.value;
  draft.value = "";
  await aiChat.sendMessage({
    message,
    symbol: symbol.value,
    period: period.value,
    limit: limit.value,
    include_context: includeContext.value,
    model: selectedModel.value,
  });
  scrollToBottom();
}

function handleKeydown(event) {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    send();
  }
}

watch(
  () => trading.selectedCryptoSymbol,
  (nextSymbol) => {
    const normalized = normalizeCryptoSymbol(nextSymbol);
    if (normalized) {
      symbol.value = normalized;
    }
  },
);

watch(
  () => aiChat.drawerOpen,
  (open) => {
    if (open) {
      aiChat.fetchSessions().catch(() => {});
      scrollToBottom();
    }
  },
);

watch(
  () => aiChat.messages.length,
  () => scrollToBottom(),
);
</script>

<template>
  <Teleport to="body">
    <div v-if="aiChat.drawerOpen" class="ai-chat-backdrop" @click.self="aiChat.closeDrawer()">
      <aside class="ai-chat-drawer" aria-label="AI 项目副驾驶">
        <header class="ai-chat-header">
          <div>
            <span>AI 对话助手</span>
            <strong>项目副驾驶</strong>
          </div>
          <button class="cq-icon-button" title="关闭 AI 对话" @click="aiChat.closeDrawer()">×</button>
        </header>

        <section class="ai-chat-body">
          <aside class="ai-chat-sessions">
            <button class="cq-primary-button ai-chat-new" @click="aiChat.startNewSession()">新对话</button>
            <div class="ai-chat-session-list">
              <button
                v-for="sessionItem in aiChat.sessions"
                :key="sessionItem.session_id"
                class="ai-chat-session"
                :class="{ active: aiChat.currentSession?.session_id === sessionItem.session_id }"
                @click="aiChat.loadSession(sessionItem.session_id)"
              >
                <strong>{{ sessionItem.title || "AI 对话" }}</strong>
                <span>{{ sessionItem.last_message || "暂无消息" }}</span>
              </button>
              <p v-if="!aiChat.sessions.length && !aiChat.loadingSessions" class="ai-chat-empty">暂无历史会话</p>
            </div>
          </aside>

          <main class="ai-chat-main">
            <div class="ai-chat-context">
              <label>
                <span>交易对</span>
                <select v-model="symbol">
                  <option v-for="item in pairOptions" :key="item" :value="item">{{ item }}</option>
                </select>
              </label>
              <label>
                <span>周期</span>
                <select v-model="period">
                  <option v-for="item in periodOptions" :key="item" :value="item">{{ item }}</option>
                </select>
              </label>
              <label>
                <span>K 线</span>
                <input v-model.number="limit" type="number" min="30" max="500" step="10" />
              </label>
              <label class="ai-chat-toggle">
                <input v-model="includeContext" type="checkbox" />
                <span>带项目和行情上下文</span>
              </label>
            </div>

            <div ref="messageList" class="ai-chat-messages">
              <div v-if="!aiChat.hasMessages" class="ai-chat-welcome">
                <strong>真实交易关闭，AI 是项目副驾驶，不能直接下单。</strong>
                <p>
                  可以正常聊天，也可以问项目怎么用、每个模块做什么、策略和回测怎么理解、
                  风控为什么阻断、模拟账户和订单状态怎么看。
                </p>
                <div class="ai-chat-suggestions" aria-label="推荐问题">
                  <button
                    v-for="question in suggestedQuestions"
                    :key="question"
                    type="button"
                    @click="useSuggestedQuestion(question)"
                  >
                    {{ question }}
                  </button>
                </div>
              </div>
              <article
                v-for="message in aiChat.messages"
                :key="message.message_id"
                class="ai-chat-message"
                :class="`ai-chat-message--${message.role}`"
              >
                <span>{{ message.role === "user" ? "你" : "AI" }}</span>
                <p>{{ message.content }}</p>
              </article>
              <article v-if="aiChat.loading" class="ai-chat-message ai-chat-message--assistant">
                <span>AI</span>
                <p>正在结合项目模块、行情、账户和风控状态思考...</p>
              </article>
            </div>

            <p v-if="aiChat.errorMessage" class="ai-chat-error">{{ aiChat.errorMessage }}</p>

            <footer class="ai-chat-composer">
              <textarea
                v-model="draft"
                rows="3"
                placeholder="例如：这个项目怎么用？自动交易为什么没有下单？风控中心这些指标是什么意思？"
                @keydown="handleKeydown"
              ></textarea>
              <div class="ai-chat-actions">
                <div class="ai-chat-model-switch" aria-label="模型选择">
                  <button
                    v-for="option in modelOptions"
                    :key="option.value"
                    type="button"
                    :class="{ active: selectedModel === option.value }"
                    :title="`使用 ${option.label} 模型回复`"
                    @click="selectedModel = option.value"
                  >
                    {{ option.label }}
                  </button>
                </div>
                <button
                  class="cq-outline-button"
                  :disabled="!aiChat.currentSession"
                  @click="aiChat.deleteSession()"
                >
                  删除会话
                </button>
                <button class="cq-primary-button" :disabled="!canSend" @click="send">
                  {{ aiChat.loading ? "思考中" : "发送" }}
                </button>
              </div>
            </footer>
          </main>
        </section>
      </aside>
    </div>
  </Teleport>
</template>
