<script setup>
import { onMounted, ref, watch } from 'vue'
import { getJSON } from '../api'

const rows = ref([])
const data = ref(null)
const statusFilter = ref('pending')
const err = ref('')

async function load() {
  err.value = ''
  try {
    const qs = statusFilter.value === 'all' ? '?status=all' : `?status=${statusFilter.value}`
    data.value = await getJSON(`/api/bronze${qs}`)
    rows.value = data.value.rows
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(load)
watch(statusFilter, load)
</script>
<template>
  <div class="page">
    <h1>待晋升区 · Bronze</h1>
    <p class="muted">
      Ingest 只写这里，不直接写 Canonical。经晋升闸对账通过后，行才进入 Silver / Canonical；
      失败的行仍留在本区并记录失败原因。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>

    <div class="tiles" v-if="data">
      <div class="tile"><div class="hero-num">{{ data.pending_count }}</div><div class="muted">待晋升 pending</div></div>
      <div class="tile"><div class="hero-num">{{ data.promoted_count }}</div><div class="muted">已晋升 promoted</div></div>
      <div class="tile"><div class="hero-num">{{ data.total_count }}</div><div class="muted">Bronze 总行数</div></div>
    </div>

    <div class="panel">
      <label>
        状态
        <select v-model="statusFilter">
          <option value="pending">pending（待晋升）</option>
          <option value="promoted">promoted（已晋升审计）</option>
          <option value="all">全部</option>
        </select>
      </label>
      <button class="secondary" style="margin-left:0.75rem" @click="load">刷新</button>
      <router-link to="/promote" style="margin-left:0.75rem">去晋升台 →</router-link>
    </div>

    <div class="panel" v-if="data && data.by_run.length">
      <h3>按摄取批次</h3>
      <table>
        <thead><tr><th>run</th><th>待晋升</th><th>已晋升</th><th>总计</th></tr></thead>
        <tbody>
          <tr v-for="b in data.by_run" :key="b.run_id">
            <td>#{{ b.run_id }}</td>
            <td>{{ b.pending_count }}</td>
            <td>{{ b.promoted_count }}</td>
            <td>{{ b.total_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <p>当前筛选共 <strong>{{ rows.length }}</strong> 行</p>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>run</th><th>source</th><th>key</th><th>title</th><th>price</th>
            <th>event_ts</th><th>rev</th><th>disposition</th><th>status</th><th>失败原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.run_id }}</td>
            <td>{{ r.source_id }}</td>
            <td class="mono">{{ r.business_key }}</td>
            <td>{{ r.title }}</td>
            <td class="mono">{{ r.price }}</td>
            <td class="mono">{{ r.event_ts }}</td>
            <td>{{ r.source_revision }}</td>
            <td><span class="tag" :class="r.disposition === 'upsert' ? 'warn' : 'ok'">{{ r.disposition }}</span></td>
            <td><span class="tag" :class="r.status === 'promoted' ? 'ok' : 'warn'">{{ r.status }}</span></td>
            <td class="muted">{{ r.failure_reason || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="muted">该状态下暂无行。</p>
    </div>
  </div>
</template>
