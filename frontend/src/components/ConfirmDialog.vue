<script setup>
const props = defineProps({
  visible: { type: Boolean, default: false },
  title: { type: String, default: "确认操作" },
  message: { type: String, default: "确定要执行此操作吗？" },
  confirmText: { type: String, default: "确认" },
  cancelText: { type: String, default: "取消" },
  danger: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
});

const emit = defineEmits(["confirm", "cancel", "update:visible"]);

function onConfirm() {
  emit("confirm");
}

function onCancel() {
  emit("update:visible", false);
  emit("cancel");
}

function onBackdropClick(event) {
  if (event.target === event.currentTarget) {
    onCancel();
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="props.visible" class="confirm-overlay" @click="onBackdropClick">
      <div class="confirm-dialog" :class="{ 'confirm-dialog--danger': props.danger }">
        <h3 class="confirm-title">{{ props.title }}</h3>
        <p class="confirm-message">{{ props.message }}</p>
        <div class="confirm-actions">
          <button class="ghost-button" :disabled="props.loading" @click="onCancel">
            {{ props.cancelText }}
          </button>
          <button
            class="primary-button"
            :class="{ 'confirm-button--danger': props.danger }"
            :disabled="props.loading"
            @click="onConfirm"
          >
            {{ props.loading ? "处理中..." : props.confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(1, 6, 15, 0.68);
  backdrop-filter: blur(10px);
}

.confirm-dialog {
  width: min(460px, 100%);
  padding: 24px;
  border: 1px solid rgba(154, 182, 214, 0.22);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(18, 33, 55, 0.98), rgba(7, 18, 33, 0.98));
  box-shadow: 0 24px 70px rgba(1, 6, 15, 0.45);
}

.confirm-title {
  margin: 0;
  font-size: 18px;
}

.confirm-message {
  margin: 12px 0 22px;
  color: #9db0c6;
  line-height: 1.6;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.confirm-button--danger {
  background: linear-gradient(135deg, #ff6b6b, #f03e3e);
  color: #fff;
}
</style>
