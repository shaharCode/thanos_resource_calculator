let currentMode = 'manual';
let currentConfigData = {};

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function formatMib(bytes) {
    if (bytes === 0) return '0MiB';
    return Math.floor(bytes / (1024 * 1024)) + "MiB";
}

function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function copyToClipboard(text) {
    const tempInput = document.createElement("input");
    tempInput.value = text;
    document.body.appendChild(tempInput);
    tempInput.select();
    document.execCommand("copy");
    document.body.removeChild(tempInput);
    alert("Copied to clipboard!");
}

function copyConfig() {
    const text = document.getElementById('configOutput').innerText;
    const tempInput = document.createElement("textarea");
    tempInput.value = text;
    document.body.appendChild(tempInput);
    tempInput.select();
    document.execCommand("copy");
    document.body.removeChild(tempInput);
    alert("Configuration copied!");
}

// New decoupled functions for UI management
function activateTab(el) {
    document.querySelectorAll('.config-tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
    refreshConfigView();
}

function refreshConfigView() {
    const activeTab = document.querySelector('.config-tab.active');
    if (!activeTab) return;
    const key = activeTab.getAttribute('data-key');
    document.getElementById('configOutput').innerText = currentConfigData[key] || "No config available.";
}

function setMode(mode) {
    currentMode = mode;
    const btnManual = document.getElementById('btnManual');
    // btnEstimator logic removed for simplified version, but keeping function structure
    const estimatorSection = document.getElementById('estimatorInputs');

    if (mode === 'manual') {
        document.getElementById('btnManual').classList.add('active');
        // document.getElementById('btnEstimator').classList.remove('active');
    }
}

function calculate() {
    try {
        const activeSeries = parseInt(document.getElementById('activeSeries').value) || 0;
        const interval = parseInt(document.getElementById('interval').value) || 1;
        const replication = 1;
        const qps = parseInt(document.getElementById('qps').value) || 0;

        const perfFactor = parseFloat(document.getElementById('perfMode').value) || 1.3;
        const complexityBytes = parseInt(document.getElementById('queryComplexity').value) || 268435456;

        const retLocalHours = parseInt(document.getElementById('retLocalHours').value) || 6;
        const retRawDays = parseInt(document.getElementById('retRawDays').value) || 15;
        const ret5mDays = parseInt(document.getElementById('ret5mDays').value) || 0;
        const ret1hDays = parseInt(document.getElementById('ret1hDays').value) || 0;

        const dps = activeSeries / interval;
        document.getElementById('dpsResult').innerText = formatNumber(Math.floor(dps));

        // --- COMPONENTS ---

        const otelCpu = Math.ceil((dps / 10000) * perfFactor);
        const otelRamBytes = (512 * 1024 * 1024) + ((dps / 10000) * 1024 * 1024 * 1024);
        document.getElementById('otelCpu').innerText = (otelCpu < 1 ? 1 : otelCpu) + " vCPU";
        document.getElementById('otelRam').innerText = formatBytes(otelRamBytes);

        let routerReplicas = Math.ceil(dps / 30000);
        if (routerReplicas < 2) routerReplicas = 2;
        const routerCpu = Math.ceil((routerReplicas * 1) * perfFactor);
        const routerRamBytes = routerReplicas * 1 * 1024 * 1024 * 1024;

        document.getElementById('routerReplicas').innerText = routerReplicas + " Replicas";
        document.getElementById('routerCpu').innerHTML = `${routerCpu} vCPU <span class="per-pod">(${Math.round((routerCpu / routerReplicas) * 10) / 10} / Pod)</span>`;

        const totalReplicatedSeries = activeSeries * replication;
        const maxSeriesPerPod = 4000000;
        let ingestorShards = Math.ceil(totalReplicatedSeries / maxSeriesPerPod);
        if (ingestorShards < replication) ingestorShards = replication;

        const maxReceiverQueryMem = 300 * 1024 * 1024;
        const effectiveReceiverComplexity = Math.min(complexityBytes, maxReceiverQueryMem);
        const receiveQueryRamOverhead = qps * effectiveReceiverComplexity;
        const thanosRamBytes = (totalReplicatedSeries * 4096) + receiveQueryRamOverhead;
        const ingestorRamPerPod = thanosRamBytes / ingestorShards;

        const walBytes = dps * 7200 * 3 * replication * 1.5;
        let localTsdbBytes = 0;
        if (retLocalHours > 2) {
            const retentionSeconds = (retLocalHours - 2) * 3600;
            localTsdbBytes = dps * retentionSeconds * 1.5 * replication;
        }
        const totalReceiverDisk = walBytes + localTsdbBytes;

        const receiveIngestCpu = (dps * replication) / 15000;
        const receiveQueryCpu = qps / 5;
        const receiveCpu = Math.ceil((receiveIngestCpu + receiveQueryCpu) * perfFactor);

        document.getElementById('ingestorShards').innerText = ingestorShards + " Pods";
        document.getElementById('thanosRam').innerHTML = `${formatBytes(thanosRamBytes)} <span class="per-pod">(${formatBytes(ingestorRamPerPod)} / Pod)</span>`;
        document.getElementById('thanosDisk').innerHTML = `${formatBytes(totalReceiverDisk)} <span class="per-pod">(${formatBytes(totalReceiverDisk / ingestorShards)} / Pod)</span>`;
        document.getElementById('thanosCpu').innerHTML = `${receiveCpu} vCPU <span class="per-pod">(${(receiveCpu / ingestorShards).toFixed(1)} / Pod)</span>`;

        const safeReceiveRequestLimit = Math.max(20000000, activeSeries * 20);
        document.getElementById('safeReceiveRequestLimit').innerText = safeReceiveRequestLimit.toExponential(1);

        const safeReceiveConcurrency = Math.max(50, Math.ceil((activeSeries / interval) / 250));
        document.getElementById('safeReceiveConcurrency').innerText = safeReceiveConcurrency;

        // Adjust series/sample limits based on active series size - for config only/info
        const safeSeriesLimit = Math.max(50000, Math.min(500000, Math.ceil(activeSeries / 50)));

        const s3RawBytes = dps * 86400 * retRawDays * 1.5;
        const s35mBytes = (dps / 300) * 86400 * ret5mDays * 5 * 2;
        const s31hBytes = (dps / 3600) * 86400 * ret1hDays * 5 * 2;
        const totalS3Bytes = s3RawBytes + s35mBytes + s31hBytes;

        document.getElementById('s3Storage').innerText = formatBytes(totalS3Bytes);
        document.getElementById('valRaw').innerText = formatBytes(s3RawBytes);
        document.getElementById('val5m').innerText = formatBytes(s35mBytes);
        document.getElementById('val1h').innerText = formatBytes(s31hBytes);

        // Calc daily generation size (approx 1.5 bytes per sample)
        const dailyGenBytes = dps * 86400 * 1.5;
        // Compactor works on max 2-week blocks (usually). Cap validation at 14d or RawRetention
        const maxBlockDays = Math.min(retRawDays, 14);

        // Recommended: 3x the max block size being compacted
        const compactorScratchBytes = dailyGenBytes * maxBlockDays * 3;

        let compactorRamGB = 2;
        if (activeSeries > 1000000) compactorRamGB = 8;
        if (activeSeries > 5000000) compactorRamGB = 16;
        const compactorRamBytes = compactorRamGB * 1024 * 1024 * 1024;
        const compactorCpu = 1;
        const compactorReplicas = 1;

        document.getElementById('compactDisk').innerText = formatBytes(compactorScratchBytes);
        document.getElementById('compactRam').innerText = compactorRamGB + " GB";
        document.getElementById('compactCpu').innerText = compactorCpu + " vCPU";

        const storeCacheBytes = (totalS3Bytes * 0.002) + (1 * 1024 * 1024 * 1024);
        const storeQueryOverhead = qps * complexityBytes;
        const storeRamTotal = storeCacheBytes + storeQueryOverhead;

        let baseStoreCpu = (activeSeries / 1500000) + (qps / 15);
        let storeCpu = Math.ceil(baseStoreCpu * perfFactor);
        if (storeCpu < 1) storeCpu = 1;

        // Forced static 1 as requested
        let storeReplicas = 1;
        // let storeReplicas = Math.ceil(storeCpu / 2);
        // if (storeReplicas < 1) storeReplicas = 1;

        if (storeCpu < storeReplicas) storeCpu = storeReplicas;

        const storeRamPerPod = storeRamTotal / storeReplicas;
        const storePvcPerReplica = totalS3Bytes * 0.02;
        const storePvcTotal = storePvcPerReplica * storeReplicas;

        document.getElementById('storeReplicas').innerText = storeReplicas + " Replicas";
        document.getElementById('storeRam').innerHTML = `${formatBytes(storeRamTotal)} <span class="per-pod">(${formatBytes(storeRamPerPod)} / Pod)</span>`;
        document.getElementById('storeCpu').innerHTML = `${storeCpu} vCPU <span class="per-pod">(${(storeCpu / storeReplicas).toFixed(1)} / Pod)</span>`;
        document.getElementById('storePvc').innerHTML = `${formatBytes(storePvcTotal)} <span class="per-pod">(${formatBytes(storePvcPerReplica)} / Pod)</span>`;

        let frontendReplicas = 1 + Math.floor(qps / 50);
        const frontendCpu = Math.ceil((frontendReplicas * 1) * perfFactor);
        const frontendRamBytes = frontendReplicas * 2 * 1024 * 1024 * 1024;
        document.getElementById('frontendReplicas').innerText = frontendReplicas + " Replicas";
        document.getElementById('frontendCpuVal').innerHTML = `${frontendCpu} vCPU <span class="per-pod">(${Math.round((frontendCpu / frontendReplicas) * 10) / 10} / Pod)</span>`;
        document.getElementById('frontendRamVal').innerHTML = `${formatBytes(frontendRamBytes)} <span class="per-pod">(2GB / Pod)</span>`;

        let querierReplicas = 1 + Math.floor(qps / 20);
        const querierCpu = Math.ceil((querierReplicas * 2) * perfFactor);
        const querierRamBytes = (1 * 1024 * 1024 * 1024) + (qps * complexityBytes);
        const querierRamPerPod = querierRamBytes / querierReplicas;

        document.getElementById('querierReplicas').innerText = querierReplicas + " Replicas";
        document.getElementById('querierCpuVal').innerHTML = `${querierCpu} vCPU <span class="per-pod">(${Math.round((querierCpu / querierReplicas) * 10) / 10} / Pod)</span>`;
        document.getElementById('querierRamVal').innerHTML = `${formatBytes(querierRamBytes)} <span class="per-pod">(${formatBytes(querierRamPerPod)} / Pod)</span>`;

        const safeQueryConcurrent = Math.max(20, Math.ceil(qps * 2));
        document.getElementById('safeQueryConcurrent').innerText = safeQueryConcurrent;
        const safeStoreConcurrency = Math.max(20, Math.ceil(qps * 2));
        document.getElementById('safeStoreConcurrency').innerText = safeStoreConcurrency;
        const safeStoreSampleLimit = Math.max(5000000, Math.ceil(activeSeries * 1.5));
        document.getElementById('safeStoreSampleLimit').innerText = safeStoreSampleLimit.toExponential(1);

        const totalThanosPods = routerReplicas + ingestorShards + 1 + storeReplicas + frontendReplicas + querierReplicas;
        const finalTotalCpu = otelCpu + routerCpu + receiveCpu + compactorCpu + storeCpu + frontendCpu + querierCpu;
        const totalRam = otelRamBytes + routerRamBytes + thanosRamBytes + storeRamTotal + frontendRamBytes + querierRamBytes + compactorRamBytes;
        const totalPvc = totalReceiverDisk + compactorScratchBytes + storePvcTotal;

        document.getElementById('totalPods').innerText = totalThanosPods;
        document.getElementById('totalCpu').innerText = finalTotalCpu + " vCPU";
        document.getElementById('totalRam').innerText = formatBytes(totalRam);
        document.getElementById('totalPvc').innerText = formatBytes(totalPvc);
        document.getElementById('totalS3').innerText = formatBytes(totalS3Bytes);

        const perfText = perfFactor === 1.0 ? "Cost Optimized" : (perfFactor === 2.0 ? "Low Latency" : "Balanced");
        const explanation = `
                <div style="margin-bottom:8px; color:var(--perf-color);"><strong>🚀 Performance Mode: ${perfText}</strong> <br>
                Added a ${perfFactor}x CPU factor to keep utilization low and improve latency.</div>
                
                <div style="margin-bottom:8px">1. <strong>Query Complexity Factor:</strong> <br>
                Added complexity multiplier. Heavy queries (days range) double memory requirements for Querier and Store Gateway to prevent OOM.</div>

                <div style="margin-bottom:8px">2. <strong>Receiver Storage:</strong> <br>
                All data is stored on ${ingestorShards} Ingestor Pods. Total Volume: <strong>${formatBytes(totalReceiverDisk)}</strong>.</div>
            `;
        document.getElementById('explanationText').innerHTML = explanation;

        // Generate Config Data
        currentConfigData['receive'] = `# Thanos Receiver Ingestor (${ingestorShards} Replicas)
# -----------------------------------------------------
# Note: request limits (series/samples) should be set in
# a limits configuration file (e.g. --receive.tenant-limit-config-file)
# or via --receive.default-tenant-limit.* flags if available.

args:
  - receive
  - --tsdb.retention.time=${retLocalHours}h
  - --receive.remote-write.server-max-concurrency=${safeReceiveConcurrency}
  - --store.limits.request-samples=${safeReceiveRequestLimit.toExponential(1)}
  - --objstore.config-file=/etc/thanos/bucket.yml
  - --auto-gomemlimit.ratio=0.9

env:
  - name: GOGC
    value: "100"`;

        currentConfigData['store'] = `# Thanos Store Gateway (${storeReplicas} Replicas)
# -----------------------------------------------------
args:
  - store
  - --index-cache-size=${formatMib(storeRamPerPod * 0.5)}  # ~50% of Pod RAM for Cache
  - --chunk-pool-size=${formatMib(storeRamPerPod * 0.3)}   # ~30% for Chunk Pool
  - --store.grpc.series-max-concurrency=${safeStoreConcurrency}
  - --store.grpc.series-sample-limit=${safeStoreSampleLimit.toExponential(1)}
  - --objstore.config-file=/etc/thanos/bucket.yml
  - --auto-gomemlimit.ratio=0.9

env:
  # No GOMEMLIMIT env needed if using auto-gomemlimit flag`;

        currentConfigData['query'] = `# Thanos Querier (${querierReplicas} Replicas)
# -----------------------------------------------------
args:
  - query
  - --query.max-concurrent=${safeQueryConcurrent}
  - --query.timeout=2m
  - --query.replica-label=replica
  - --auto-gomemlimit.ratio=0.9
  
env:
  # No GOMEMLIMIT env needed if using auto-gomemlimit flag`;

        currentConfigData['compactor'] = `# Thanos Compactor (Singleton)
# -----------------------------------------------------
args:
  - compact
  - --compact.concurrency=1
  - --retention.resolution-raw=${retRawDays}d
  - --retention.resolution-5m=${ret5mDays}d
  - --retention.resolution-1h=${ret1hDays}d
  - --objstore.config-file=/etc/thanos/bucket.yml
  - --auto-gomemlimit.ratio=0.9

env:
  # No GOMEMLIMIT env needed if using auto-gomemlimit flag`;

        currentConfigData['frontend'] = `# Thanos Query Frontend (${frontendReplicas} Replicas)
# -----------------------------------------------------
args:
  - query-frontend
  - --query-range.split-interval=24h
  - --query-range.align-range-with-step=true
  - --query-range.max-retries-per-request=5
  - --query-range.response-cache-config-file=/etc/thanos/cache.yml
  - --auto-gomemlimit.ratio=0.9

env:
  # No GOMEMLIMIT env needed if using auto-gomemlimit flag`;

        refreshConfigView();
    } catch (e) {
        console.error("Calculation Error:", e);
    }
}

const inputs = document.querySelectorAll('input, select');
inputs.forEach(input => {
    if (!input.id.startsWith('est')) {
        input.addEventListener('input', () => {
            if (currentMode === 'manual') calculate();
            else if (input.id !== 'activeSeries') calculate();
        });
    }
});

// Run initial calc immediately
calculate();

// Make necessary functions global so they can be called from HTML onclick attributes
window.setMode = setMode;
window.activateTab = activateTab;
window.copyConfig = copyConfig;
window.copyToClipboard = copyToClipboard;
window.calculate = calculate;
