<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { useCopilotContext } from "../composables/useCopilotContext";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useAiChatStore } from "../stores/aiChat";
import { useTradingStore } from "../stores/trading";

const props = defineProps({
  surface: {
    type: String,
    default: "overlay",
    validator: (value) => ["overlay", "rail"].includes(value),
  },
});

const router = useRouter();
const aiChat = useAiChatStore();
const trading = useTradingStore();

const draft = ref("");
const symbol = ref(normalizeCryptoSymbol(trading.selectedCryptoSymbol || "BTC/USDT"));
const period = ref(trading.selectedCryptoPeriod || "1h");
const limit = ref(120);
const includeContext = ref(true);
const guideMode = ref(false);
const selectedGuideGoal = ref("");
const selectedModel = ref("deepseek-v4-flash");
const messageList = ref(null);
const contextNotice = ref("");
const CHAT_DRAFT_LIMIT = 500;

const periodOptions = ["1m", "5m", "15m", "1h", "4h", "1d"];
const modelOptions = [
  { label: "Flash", value: "deepseek-v4-flash" },
  { label: "Pro", value: "deepseek-v4-pro" },
];

const {
  currentRoutePath,
  currentModule,
  currentModuleLabel,
  currentViewTitle,
  suggestedQuestions,
  guideActions,
  visibleContext,
} = useCopilotContext({
  symbol,
  period,
  limit,
  selectedModel,
  includeContext,
  guideMode,
  selectedGuideGoal,
});

const pairOptions = computed(() => {
  const base = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", ...(trading.cryptoWatchSymbols || [])];
  return [...new Set(base.map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
});
const canSend = computed(() => draft.value.trim().length > 0 && !aiChat.loading);
const draftLength = computed(() => draft.value.length);
const isRail = computed(() => props.surface === "rail");
const shellClass = computed(() => (isRail.value ? "ai-chat-rail-shell" : "ai-chat-backdrop"));
const panelClass = computed(() => ["ai-chat-drawer", isRail.value ? "ai-chat-drawer--rail" : "ai-chat-drawer--overlay"]);
const visibleActionCards = computed(() => aiChat.latestActionCards || []);

function scrollToBottom() {
  nextTick(() => {
    if (messageList.value) {
      messageList.value.scrollTop = messageList.value.scrollHeight;
    }
  });
}

function useSuggestedQuestion(question) {
  guideMode.value = false;
  selectedGuideGoal.value = "";
  draft.value = String(question || "").slice(0, CHAT_DRAFT_LIMIT);
}

function useGuideAction(action) {
  guideMode.value = true;
  selectedGuideGoal.value = String(action || "").trim();
  draft.value = selectedGuideGoal.value.slice(0, CHAT_DRAFT_LIMIT);
}

function handleActionCard(card) {
  const actionType = String(card?.action_type || "");
  if ((actionType === "navigate" || actionType === "inspect") && card?.target_route) {
    router.push(String(card.target_route));
    return;
  }
  if (actionType === "explain" || actionType === "inspect") {
    guideMode.value = true;
    selectedGuideGoal.value = String(card?.title || "解释当前页面");
    draft.value = `${selectedGuideGoal.value}：${String(card?.description || "请结合当前页面状态说明。")}`.slice(
      0,
      CHAT_DRAFT_LIMIT,
    );
  }
}

async function send() {
  if (!canSend.value) {
    return;
  }
  const message = draft.value.trim();
  draft.value = "";
  try {
    await aiChat.sendMessage({
      message,
      symbol: symbol.value,
      period: period.value,
      limit: limit.value,
      include_context: includeContext.value,
      model: selectedModel.value,
      current_route: currentRoutePath.value,
      current_module: currentModule.value,
      current_view_title: String(currentViewTitle.value || ""),
      visible_context: visibleContext.value,
      guide_mode: guideMode.value,
      user_goal: guideMode.value ? selectedGuideGoal.value || message : "",
    });
  } catch (error) {
    draft.value = message;
  } finally {
    scrollToBottom();
  }
}

function handleKeydown(event) {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    send();
  }
}

function syncDraft(event) {
  draft.value = String(event?.target?.value || "").slice(0, CHAT_DRAFT_LIMIT);
}

function handleShellClick() {
  if (!isRail.value) {
    aiChat.closeDrawer();
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
  { immediate: true },
);

watch(
  () => aiChat.messages.length,
  () => scrollToBottom(),
);

watch(
  currentModuleLabel,
  (nextLabel, previousLabel) => {
    if (previousLabel && nextLabel !== previousLabel) {
      contextNotice.value = `上下文已切换到：${nextLabel}`;
      window.setTimeout(() => {
        if (contextNotice.value === `上下文已切换到：${nextLabel}`) {
          contextNotice.value = "";
        }
      }, 2600);
    }
  },
);
</script>

<template>
  <div v-if="aiChat.drawerOpen" :class="shellClass" @click.self="handleShellClick">
    <aside :class="panelClass" aria-label="AI 项目副驾驶">
      <header class="ai-chat-header">
        <div>
          <span>AI 对话助手</span>
          <strong>量化副驾驶</strong>
          <small>AI 只做建议、解释和引导，不能直接下单</small>
        </div>
        <button class="cq-icon-button" title="关闭 AI 助手" aria-label="关闭 AI 助手" @click="aiChat.closeDrawer()">×</button>
      </header>

      <section class="ai-chat-context-bar" aria-label="当前助手上下文">
        <strong>{{ currentModuleLabel }}</strong>
        <span>{{ symbol }} · {{ period }} · {{ selectedModel.includes("pro") ? "Pro" : "Flash" }}</span>
        <small>{{ includeContext ? "带项目和行情上下文" : "仅项目说明" }}</small>
      </section>
      <p v-if="contextNotice" class="ai-chat-context-notice">{{ contextNotice }}</p>

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
            <label class="ai-chat-toggle">
              <input v-model="guideMode" type="checkbox" />
              <span>引导模式</span>
            </label>
          </div>

          <div ref="messageList" class="ai-chat-messages">
            <div v-if="!aiChat.hasMessages" class="ai-chat-welcome">
              <strong>真实交易关闭，AI 是项目副驾驶，不会替你点击或下单。</strong>
              <p>
                可以正常聊天，也可以问项目怎么用、每个模块做什么、策略和回测如何理解、
                风控中心为什么阻断、模拟账户和订单状态怎么看。
              </p>
              <span class="ai-chat-section-title">问项目问题</span>
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
              <div class="ai-chat-guide" aria-label="引导模式">
                <span class="ai-chat-section-title">让我一步一步带你操作</span>
                <button
                  v-for="action in guideActions"
                  :key="action"
                  type="button"
                  @click="useGuideAction(action)"
                >
                  {{ action }}
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
              <p>正在结合当前页面、项目模块、行情、账户和风控状态思考...</p>
            </article>

            <div v-if="visibleActionCards.length" class="ai-chat-action-cards" aria-label="AI 安全动作卡片">
              <button
                v-for="card in visibleActionCards"
                :key="card.id || card.title"
                type="button"
                class="ai-chat-action-card"
                :data-action-card-id="card.id"
                @click="handleActionCard(card)"
              >
                <strong>{{ card.title }}</strong>
                <span>{{ card.description }}</span>
                <small>{{ card.action_type }} · {{ card.risk_level || "safe" }}</small>
              </button>
            </div>
          </div>

          <p v-if="aiChat.errorMessage" class="ai-chat-error">{{ aiChat.errorMessage }}</p>

          <footer class="ai-chat-composer">
            <textarea
              v-model="draft"
              data-ai-drawer-input="message"
              :maxlength="CHAT_DRAFT_LIMIT"
              rows="3"
              placeholder="例如：这个页面怎么用？为什么这里没有下单？这个风控阻断是什么意思？"
              @input="syncDraft"
              @compositionend="syncDraft"
              @keydown="handleKeydown"
            ></textarea>
            <div class="ai-chat-actions">
              <span class="ai-chat-draft-count" data-ai-drawer-count="message">{{ draftLength }}/{{ CHAT_DRAFT_LIMIT }}</span>
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
              <button class="cq-outline-button" :disabled="!aiChat.currentSession" @click="aiChat.deleteSession()">删除会话</button>
              <button class="cq-primary-button" data-ai-drawer-send="message" :disabled="!canSend" @click="send">
                {{ aiChat.loading ? "思考中" : "发送" }}
              </button>
            </div>
          </footer>
        </main>
      </section>
    </aside>
  </div>
</template>
