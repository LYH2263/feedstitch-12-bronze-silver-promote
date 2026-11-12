<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const sources = ref([])
const sourceId = ref(null)
const mode = ref('incremental')
const last = ref(null)
const history = ref([])
const err = ref('')
const busy = ref(false)

async function refresh() {
  history.value = await getJSON('/api/runs')
}

async function runOnce() {
  err.value = ''
  busy.value = true
  try {
    last.value = await postJSON(`/api/sources/${sourceId.value}/runs`, { mode: mode.value })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  sources.value = await getJSON('/api/sources')
  if (sources.value.length) sourceId.value = sources.value[0].id
  await refresh()
})
</script>
<template>
  <div class="page">
    <h1>运行台</h1>
    <p class="muted">选源触发增量或全量；解析 / 去重 / 冲突隔离后先落待晋升区，晋升闸通过才写 Canonical。</p>
    <div class="panel">
      <label>
        源
        <select v-model.number="sourceId">
          <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.id }}. {{ s.name }}</option>
        </select>
      </label>
      <label style="margin-left:1rem">
        模式
        <select v-model="mode">
          <option value="incremental">incremental</option>
          <option value="full">full</option>
        </select>
      </label>
      <button style="margin-left:1rem" :disabled="busy || !sourceId" @click="runOnce">
        {{ busy ? '运行中…' : '执行 Run' }}
      </button>
    </div>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="last">
      <h3>最近一次报告</h3>
      <p>
        Run #{{ last.id }} ·
        <span class="tag ok">{{ last.status }}</span> ·
        parsed {{ last.parsed_count }} /
        入待晋升 {{ last.upserted_count }} /
        conflict {{ last.conflict_count }} /
        skipped {{ last.skipped_count }}
      </p>
      <p class="mono muted">
        bronze_candidates={{ last.report?.bronze_candidate_count }}
        bronze_keys={{ (last.report?.bronze_business_keys || []).length }}
        bronze_pending={{ last.report?.bronze_pending_count }}
        canonical_count={{ last.report?.canonical_count }}
        watermark={{ last.report?.watermark_ts }}
      </p>
      <router-link to="/promote">去晋升台处理这批候选 →</router-link>
    </div>
    <div class="panel">
      <h3>历史 Runs</h3>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>源</th><th>模式</th><th>状态</th><th>parsed</th><th>入待晋升</th><th>conflict</th><th>skipped</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in history" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.source_name }}</td>
            <td>{{ r.mode }}</td>
            <td><span class="tag" :class="r.status === 'ok' ? 'ok' : 'danger'">{{ r.status }}</span></td>
            <td>{{ r.parsed_count }}</td>
            <td>{{ r.upserted_count }}</td>
            <td>{{ r.conflict_count }}</td>
            <td>{{ r.skipped_count }}</td>
            <td class="mono">{{ r.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
