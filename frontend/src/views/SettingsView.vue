<script setup>
import { onMounted } from "vue";

import { useSettingsData } from "../composables/useSettingsData";

const settings = useSettingsData();

onMounted(() => {
  settings.refreshSettings();
});
</script>

<template>
  <section class="workspace-grid workspace-grid--stacked settings-view">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">System Settings</span>
          <h3>系统设置</h3>
        </div>
        <button class="ghost-button" @click="settings.refreshSettings">刷新设置</button>
      </div>
      <p class="helper-text">真实交易保持关闭；AI 只提供建议，不会自动下单。</p>
    </article>

    <section class="workspace-grid">
      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">Safety</span>
            <h3>安全边界</h3>
          </div>
        </div>
        <dl class="detail-list">
          <div v-for="item in settings.safetySettings.value" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd><span class="status-chip" :class="item.tone">{{ item.value }}</span></dd>
          </div>
        </dl>
      </article>

      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">Workspace</span>
            <h3>工作台偏好</h3>
          </div>
        </div>
        <dl class="detail-list">
          <div v-for="item in settings.preferenceSettings.value" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd>{{ item.value }}</dd>
          </div>
          <div>
            <dt>提醒音效</dt>
            <dd>
              <label class="inline-check">
                <input v-model="settings.soundEnabled.value" type="checkbox" />
                <span>{{ settings.soundEnabled.value ? "开启" : "关闭" }}</span>
              </label>
            </dd>
          </div>
        </dl>
      </article>
    </section>

    <section class="workspace-grid">
      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">AI Provider</span>
            <h3>AI / DeepSeek 状态</h3>
          </div>
        </div>
        <dl class="detail-list">
          <div v-for="item in settings.aiSettings.value" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd>{{ item.value }}</dd>
          </div>
        </dl>
      </article>

      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">Connections</span>
            <h3>连接状态</h3>
          </div>
        </div>
        <dl class="detail-list">
          <div v-for="item in settings.connectionSettings.value" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd>{{ item.value }}</dd>
          </div>
        </dl>
      </article>
    </section>
  </section>
</template>
