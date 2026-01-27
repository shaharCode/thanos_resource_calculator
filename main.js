// Vercel Web Analytics integration removed (requires build step)


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

    if (mode === 'manual') {
        document.getElementById('btnManual').classList.add('active');
    }
}

async function calculate() {
    try {
        const payload = {
            activeSeries: parseInt(document.getElementById('activeSeries').value) || 0,
            interval: parseInt(document.getElementById('interval').value) || 1,
            qps: parseInt(document.getElementById('qps').value) || 0,
            perfFactor: parseFloat(document.getElementById('perfMode').value) || 1.3,
            queryComplexity: parseInt(document.getElementById('queryComplexity').value) || 268435456,
            retLocalHours: parseInt(document.getElementById('retLocalHours').value) || 6,
            retRawDays: parseInt(document.getElementById('retRawDays').value) || 15,
            ret5mDays: parseInt(document.getElementById('ret5mDays').value) || 0,
            ret1hDays: parseInt(document.getElementById('ret1hDays').value) || 0
        };

        const response = await fetch('/api/calculate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            console.error('Calculation failed');
            return;
        }

        const data = await response.json();
        const m = data.metrics;
        currentConfigData = data.configs; // Update configs

        // Update UI
        document.getElementById('dpsResult').innerText = formatNumber(m.dps);

        // OTel
        document.getElementById('otelCpu').innerText = (m.otelCpu < 1 ? 1 : m.otelCpu) + " vCPU";
        document.getElementById('otelRam').innerText = formatBytes(m.otelRamBytes);

        // Router
        document.getElementById('routerReplicas').innerText = m.routerReplicas + " Replicas";
        document.getElementById('routerCpu').innerHTML = `${m.routerCpu} vCPU <span class="per-pod">(${Math.round((m.routerCpu / m.routerReplicas) * 10) / 10} / Pod)</span>`;

        // Ingestor
        document.getElementById('ingestorShards').innerText = m.ingestorShards + " Pods";
        document.getElementById('thanosRam').innerHTML = `${formatBytes(m.thanosRamBytes)} <span class="per-pod">(${formatBytes(m.ingestorRamPerPod)} / Pod)</span>`;
        document.getElementById('thanosDisk').innerHTML = `${formatBytes(m.totalReceiverDisk)} <span class="per-pod">(${formatBytes(m.receiverDiskPerPod)} / Pod)</span>`;
        document.getElementById('thanosCpu').innerHTML = `${m.receiveCpu} vCPU <span class="per-pod">(${(m.receiveCpu / m.ingestorShards).toFixed(1)} / Pod)</span>`;

        // Safety
        document.getElementById('safeReceiveRequestLimit').innerText = m.safeReceiveRequestLimit.toExponential(1);
        document.getElementById('safeReceiveConcurrency').innerText = m.safeReceiveConcurrency;
        document.getElementById('safeQueryConcurrent').innerText = m.safeQueryConcurrent;
        document.getElementById('safeStoreConcurrency').innerText = m.safeStoreConcurrency;
        document.getElementById('safeStoreSampleLimit').innerText = m.safeStoreSampleLimit.toExponential(1);


        // S3
        document.getElementById('s3Storage').innerText = formatBytes(m.totalS3Bytes);
        document.getElementById('valRaw').innerText = formatBytes(m.s3RawBytes);
        document.getElementById('val5m').innerText = formatBytes(m.s35mBytes);
        document.getElementById('val1h').innerText = formatBytes(m.s31hBytes);

        // Compactor
        document.getElementById('compactDisk').innerText = formatBytes(m.compactorScratchBytes);
        document.getElementById('compactRam').innerText = m.compactorRamGB + " GB";
        document.getElementById('compactCpu').innerText = m.compactorCpu + " vCPU";

        // Store
        document.getElementById('storeReplicas').innerText = m.storeReplicas + " Replicas";
        document.getElementById('storeRam').innerHTML = `${formatBytes(m.storeRamTotal)} <span class="per-pod">(${formatBytes(m.storeRamPerPod)} / Pod)</span>`;
        document.getElementById('storeCpu').innerHTML = `${m.storeCpu} vCPU <span class="per-pod">(${(m.storeCpuPerPod).toFixed(1)} / Pod)</span>`;
        document.getElementById('storePvc').innerHTML = `${formatBytes(m.storePvcTotal)} <span class="per-pod">(${formatBytes(m.storePvcPerReplica)} / Pod)</span>`;

        const tipEl = document.getElementById('storePartitionTip');
        if (tipEl) {
            tipEl.style.display = m.storePartitionTip ? 'block' : 'none';
        }

        // Frontend
        document.getElementById('frontendReplicas').innerText = m.frontendReplicas + " Replicas";
        document.getElementById('frontendCpuVal').innerHTML = `${m.frontendCpu} vCPU <span class="per-pod">(${Math.round(m.frontendCpuPerPod * 10) / 10} / Pod)</span>`;
        document.getElementById('frontendRamVal').innerHTML = `${formatBytes(m.frontendRamBytes)} <span class="per-pod">(2GB / Pod)</span>`;

        // Querier
        document.getElementById('querierReplicas').innerText = m.querierReplicas + " Replicas";
        document.getElementById('querierCpuVal').innerHTML = `${m.querierCpu} vCPU <span class="per-pod">(${Math.round(m.querierCpuPerPod * 10) / 10} / Pod)</span>`;
        document.getElementById('querierRamVal').innerHTML = `${formatBytes(m.querierRamBytes)} <span class="per-pod">(${formatBytes(m.querierRamPerPod)} / Pod)</span>`;

        // Totals
        document.getElementById('totalPods').innerText = m.totalThanosPods;
        document.getElementById('totalCpu').innerText = m.finalTotalCpu + " vCPU";
        document.getElementById('totalRam').innerText = formatBytes(m.totalRam);
        document.getElementById('totalPvc').innerText = formatBytes(m.totalPvc);
        document.getElementById('totalS3').innerText = formatBytes(m.totalS3Bytes);

        // Explanation
        document.getElementById('explanationText').innerHTML = data.explanation;

        refreshConfigView();

    } catch (e) {
        console.error("Calculation Error:", e);
    }
}

const inputs = document.querySelectorAll('input, select');
inputs.forEach(input => {
    if (!input.id.startsWith('est')) {
        input.addEventListener('input', () => {
            calculate();
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

