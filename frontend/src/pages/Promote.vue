<script setup>
import { onMounted, ref, computed } from 'vue'
import { getJSON, postJSON } from '../api'

const bronze = ref(null)
const canonical = ref([])
const batches = ref([])
const selectedRun = ref('')
const last = ref(null)
const err = ref('')
const msg = ref('')
const busy = ref(false)

const runOptions = computed(() => {
  if (!bronze.value) return []
  return bronze.value.by_run
    .filter((b) => b.pending_count > 0)
    .map((b) => ({ run_id: b.run_id, pending: b.pending_count }))
})

async function refresh() {
  const [b, c, p] = await Promise.all([
    getJSON('/api/bronze'),
    getJSON('/api/canonical'),
    getJSON('/api/promotions'),
  ])
  bronze.value = b
  canonical.value = c
  batches.value = p
}

async function promote() {
  err.value = ''
  msg.value = ''
  busy.value = true
  try {
    const body = selectedRun.value === '' ? {} : { run_id: Number(selectedRun.value) }
    last.value = await postJSON('/api/promotions', body)
    msg.value = last.value.status === 'passed'
      ? `晋升通过：候选 ${last.value.candidate_count} / 成功 ${last.value.success_count} / 失败 ${last.value.failure_count}`
      : `晋升失败：候选 ${last.value.candidate_count} / 成功 ${last.value.success_count} / 失败 ${last.value.failure_count}，行已保留在待晋升区`
    await refresh()
    selectedRun.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>
<template>
  <div class="page">
    <h1>晋升台 · Bronze → Silver</h1>
    <p class="muted">
      对选定摄取批次或全部待晋升行做对账闸：核对条数与业务键集合必须与摄取报告一致。
      通过才写 Canonical；失败则整批留在待晋升区，绝不部分静默丢数。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="msg" class="tag" :class="last && last.status === 'passed' ? 'ok' : 'danger'">{{ msg }}</p>

    <div class="panel">
      <label>
        晋升范围
        <select v-model="selectedRun">
          <option value="">全部待晋升（{{ bronze?.pending_count ?? 0 }} 行）</option>
          <option v-for="o in runOptions" :key="o.run_id" :value="o.run_id">
            Run #{{ o.run_id }}（{{ o.pending }} 行待晋升）
          </option>
        </select>
      </label>
      <button style="margin-left:0.75rem" :disabled="busy" @click="promote">
        {{ busy ? '对账中…' : '执行晋升' }}
      </button>
      <span class="muted" style="margin-left:0.75rem">
        待晋升 {{ bronze?.pending_count ?? 0 }} · Canonical {{ canonical.length }}
      </span>
    </div>

    <div class="panel" v-if="last">
      <h3>本次晋升报告 #{{ last.id }}</h3>
      <p>
        <span class="tag" :class="last.status === 'passed' ? 'ok' : 'danger'">{{ last.status }}</span>
        <span class="muted"> · scope {{ last.scope }}{{ last.run_id ? ` · run #${last.run_id}` : '' }} · {{ last.created_at }}</span>
      </p>
      <div class="tiles">
        <div class="tile"><div class="hero-num">{{ last.candidate_count }}</div><div class="muted">候选数 candidate</div></div>
        <div class="tile"><div class="hero-num">{{ last.success_count }}</div><div class="muted">成功数 success</div></div>
        <div class="tile"><div class="hero-num">{{ last.failure_count }}</div><div class="muted">失败数 failure</div></div>
      </div>
      <p class="mono muted">
        ingest_expected={{ last.report?.ingest_expected_count }}
        already_promoted={{ last.report?.already_promoted_count }}
        bronze_pending_after={{ last.report?.bronze_pending_count_after }}
        canonical_after={{ last.report?.canonical_count_after }}
      </p>
      <p class="muted">{{ last.report?.message }}</p>

      <div v-if="last.report?.failure_summary?.length">
        <h4>失败原因</h4>
        <table>
          <thead><tr><th>run</th><th>issues</th></tr></thead>
          <tbody>
            <tr v-for="f in last.report.failure_summary" :key="f.run_id">
              <td>#{{ f.run_id }}</td>
              <td class="mono">{{ f.issues.join(' / ') }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <details style="margin-top:0.75rem">
        <summary class="muted">对账明细（{{ last.report?.checks?.length ?? 0 }} 组）</summary>
        <table>
          <thead>
            <tr><th>run</th><th>结果</th><th>report 数</th><th>bronze 记录</th><th>本次待晋升</th><th>已晋升</th><th>issues</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in last.report?.checks || []" :key="c.run_id">
              <td>#{{ c.run_id }}</td>
              <td><span class="tag" :class="c.passed ? 'ok' : 'danger'">{{ c.passed ? 'pass' : 'fail' }}</span></td>
              <td>{{ c.expected_count }}</td>
              <td>{{ c.recorded_count }}</td>
              <td>{{ c.pending_count }}</td>
              <td>{{ c.already_promoted_count }}</td>
              <td class="mono muted">{{ c.issues.join(' / ') || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </div>

    <div class="panel">
      <h3>晋升批次历史（刷新后仍保留）</h3>
      <table>
        <thead>
          <tr><th>ID</th><th>scope</th><th>run</th><th>状态</th><th>候选</th><th>成功</th><th>失败</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td>{{ b.id }}</td>
            <td>{{ b.scope }}</td>
            <td>{{ b.run_id ? `#${b.run_id}` : '—' }}</td>
            <td><span class="tag" :class="b.status === 'passed' ? 'ok' : 'danger'">{{ b.status }}</span></td>
            <td>{{ b.candidate_count }}</td>
            <td>{{ b.success_count }}</td>
            <td>{{ b.failure_count }}</td>
            <td class="mono">{{ b.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!batches.length" class="muted">暂无晋升记录。</p>
    </div>

    <div class="two-col">
      <div class="panel">
        <h3>待晋升区 Bronze（{{ bronze?.pending_count ?? 0 }}）</h3>
        <table>
          <thead><tr><th>run</th><th>key</th><th>rev</th><th>status</th></tr></thead>
          <tbody>
            <tr v-for="r in (bronze?.rows || []).slice(0, 50)" :key="r.id">
              <td>#{{ r.run_id }}</td>
              <td class="mono">{{ r.business_key }}</td>
              <td>{{ r.source_revision }}</td>
              <td><span class="tag warn">{{ r.status }}</span></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!(bronze?.rows || []).length" class="muted">待晋升区为空。</p>
      </div>
      <div class="panel">
        <h3>正式主数据 Canonical（{{ canonical.length }}）</h3>
        <table>
          <thead><tr><th>key</th><th>title</th><th>rev</th></tr></thead>
          <tbody>
            <tr v-for="r in canonical.slice(0, 50)" :key="r.business_key">
              <td class="mono">{{ r.business_key }}</td>
              <td>{{ r.title }}</td>
              <td>{{ r.source_revision }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!canonical.length" class="muted">Canonical 为空。</p>
      </div>
    </div>
    <p class="muted">完整列表：<router-link to="/bronze">待晋升区</router-link> · <router-link to="/canonical">Canonical</router-link></p>
  </div>
</template>
<style scoped>
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
@media (max-width: 860px) {
  .two-col { grid-template-columns: 1fr; }
}
</style>
