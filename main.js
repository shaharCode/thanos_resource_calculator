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
        const r = data.resources;

        // Display DPS
        document.getElementById('dpsResult').innerText = formatNumber(r.dps);

        // Calculate totals
        const totalPods = r.otel.replicas + r.router.replicas + r.ingestor.replicas + r.compactor.replicas + r.store.replicas + r.frontend.replicas + r.querier.replicas;
        const totalCpu = r.otel.cpu + r.router.cpu + r.ingestor.cpu + r.compactor.cpu + r.store.cpu + r.frontend.cpu + r.querier.cpu;

        // Update summary
        document.getElementById('totalPods').innerText = totalPods;
        document.getElementById('totalCpu').innerText = totalCpu + " vCPU";
        document.getElementById('totalRam').innerText = r.ingestor.ram; // Placeholder - could aggregate if needed
        document.getElementById('totalPvc').innerText = r.ingestor.pvc; // Placeholder
        document.getElementById('totalS3').innerText = r.S3Size;

        // Update UI
        // OTel
        document.getElementById('otelCpu').innerText = (r.otel.cpu < 1 ? 1 : r.otel.cpu) + " vCPU";
        document.getElementById('otelRam').innerText = r.otel.ram;

        // Router
        document.getElementById('routerReplicas').innerText = r.router.replicas + " Replicas";
        document.getElementById('routerCpu').innerHTML = `${r.router.cpu} vCPU <span class="per-pod">(${Math.round((r.router.cpu / r.router.replicas) * 10) / 10} / Pod)</span>`;

        // Ingestor
        document.getElementById('ingestorShards').innerText = r.ingestor.replicas + " Pods";
        document.getElementById('thanosRam').innerHTML = `${r.ingestor.ram} <span class="per-pod">Total</span>`;
        document.getElementById('thanosDisk').innerHTML = `${r.ingestor.pvc} <span class="per-pod">Total</span>`;
        document.getElementById('thanosCpu').innerHTML = `${r.ingestor.cpu} vCPU <span class="per-pod">(${(r.ingestor.cpu / r.ingestor.replicas).toFixed(1)} / Pod)</span>`;

        // S3
        document.getElementById('s3Storage').innerText = r.S3Size;

        // Compactor
        document.getElementById('compactDisk').innerText = r.compactor.pvc;
        document.getElementById('compactRam').innerText = r.compactor.ram;
        document.getElementById('compactCpu').innerText = r.compactor.cpu + " vCPU";

        // Store
        document.getElementById('storeReplicas').innerText = r.store.replicas + " Replicas";
        document.getElementById('storeRam').innerHTML = `${r.store.ram} <span class="per-pod">(${r.store.ram} / Pod)</span>`;
        document.getElementById('storeCpu').innerHTML = `${r.store.cpu} vCPU <span class="per-pod">(${(r.store.cpu / r.store.replicas).toFixed(1)} / Pod)</span>`;
        document.getElementById('storePvc').innerHTML = `${r.store.pvc} <span class="per-pod">Total</span>`;

        // Frontend
        document.getElementById('frontendReplicas').innerText = r.frontend.replicas + " Replicas";
        document.getElementById('frontendCpuVal').innerHTML = `${r.frontend.cpu} vCPU <span class="per-pod">(${Math.round(r.frontend.cpu / r.frontend.replicas * 10) / 10} / Pod)</span>`;
        document.getElementById('frontendRamVal').innerHTML = `${r.frontend.ram} <span class="per-pod">Total</span>`;

        // Querier
        document.getElementById('querierReplicas').innerText = r.querier.replicas + " Replicas";
        document.getElementById('querierCpuVal').innerHTML = `${r.querier.cpu} vCPU <span class="per-pod">(${Math.round(r.querier.cpu / r.querier.replicas * 10) / 10} / Pod)</span>`;
        document.getElementById('querierRamVal').innerHTML = `${r.querier.ram} <span class="per-pod">Total</span>`;

        // Hide elements that are no longer provided
        const elementsToHide = ['safeReceiveRequestLimit', 'safeReceiveConcurrency', 'safeQueryConcurrent', 'safeStoreConcurrency', 'safeStoreSampleLimit', 'storePartitionTip', 'valRaw', 'val5m', 'val1h', 'explanationText', 'configOutput'];
        elementsToHide.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });

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

