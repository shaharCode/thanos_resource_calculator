// Vercel Web Analytics integration removed (requires build step)


let currentMode = 'manual';
let currentConfigData = {};

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + '' + sizes[i];
}

function formatMib(bytes) {
    if (bytes === 0) return '0Mi';
    return Math.floor(bytes / (1024 * 1024)) + "Mi";
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
        const payloadCollector = {
            activeSeries: parseInt(document.getElementById('activeSeries').value) || 0,
            interval: parseInt(document.getElementById('interval').value) || 1,
            perfFactor: parseFloat(document.getElementById('perfMode').value) || 1.3
        };

        const payloadPool = {
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

        const [resCollector, resPool] = await Promise.all([
            fetch('/api/calculate/collector_resources', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payloadCollector)
            }),
            fetch('/api/calculate/pool_resources', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payloadPool)
            })
        ]);

        if (!resCollector.ok || !resPool.ok) {
            console.error('Calculation failed');
            return;
        }

        const dataCollector = await resCollector.json();
        const dataPool = await resPool.json();

        // Helper to normalize data: map 'storage' -> 'pvc', 'ephemeralStorage' -> 'pvc'
        // Helper to parse CPU string ("1", "500m") to float
        const parseCpu = (cpuStr) => {
            if (!cpuStr) return 0;
            if (typeof cpuStr === 'number') return cpuStr; // already number
            if (cpuStr.endsWith('m')) {
                return parseFloat(cpuStr) / 1000;
            }
            return parseFloat(cpuStr);
        };

        // Helper to normalize data: map 'storage' -> 'pvc', 'ephemeralStorage' -> 'pvc'
        const normalize = (comp) => {
            if (!comp) return { replicas: 0, requests: { memory: "0Gi", cpu: "0" }, limits: { memory: "0Gi", cpu: "0" }, pvc: "0Gi", cpu: 0, ram: "0Gi" };
            return {
                replicas: comp.replicas,
                cpu: comp.requests.cpu, // keep as string for display
                cpuVal: parseCpu(comp.requests.cpu), // parsed value for totals
                ram: comp.requests.memory,
                pvc: comp.storage || comp.requests.ephemeralStorage || "0Gi"
            };
        };

        const r = {
            dps: dataCollector.dps,
            S3Size: dataPool.s3,

            otel: normalize(dataCollector),
            router: normalize(dataPool.receiver_router),
            ingestor: normalize(dataPool.receiver_ingestor),
            compactor: normalize(dataPool.compactor),
            store: normalize(dataPool.store),
            frontend: normalize(dataPool.query_frontend),
            querier: normalize(dataPool.query)
        };

        // Helper to parse "X GB" or "X MB" or "XGi" back to bytes
        function parseBytes(str) {
            if (!str || str === "0 Bytes") return 0;

            // Handle K8s style (no space, Ki/Mi/Gi)
            if (str.endsWith('Ki')) return parseFloat(str) * 1024;
            if (str.endsWith('Mi')) return parseFloat(str) * 1024 * 1024;
            if (str.endsWith('Gi')) return parseFloat(str) * 1024 * 1024 * 1024;
            if (str.endsWith('Ti')) return parseFloat(str) * 1024 * 1024 * 1024 * 1024;

            const parts = str.split(' ');
            const val = parseFloat(parts[0]);
            if (parts.length < 2) return val; // Fallback if no unit found

            const unit = parts[1];
            let multiplier = 1;
            if (unit === 'KB') multiplier = 1024;
            if (unit === 'MB') multiplier = 1024 * 1024;
            if (unit === 'GB') multiplier = 1024 * 1024 * 1024;
            if (unit === 'TB') multiplier = 1024 * 1024 * 1024 * 1024;
            return val * multiplier;
        }

        // Display DPS
        document.getElementById('dpsResult').innerText = formatNumber(r.dps);

        // Calculate totals
        const totalPods = r.otel.replicas + r.router.replicas + r.ingestor.replicas + r.compactor.replicas + r.store.replicas + r.frontend.replicas + r.querier.replicas;

        // Summing (CPU * Replicas) 
        const totalCpu = (r.otel.cpuVal * r.otel.replicas) +
            (r.router.cpuVal * r.router.replicas) +
            (r.ingestor.cpuVal * r.ingestor.replicas) +
            (r.compactor.cpuVal * r.compactor.replicas) +
            (r.store.cpuVal * r.store.replicas) +
            (r.frontend.cpuVal * r.frontend.replicas) +
            (r.querier.cpuVal * r.querier.replicas);

        // Sum Ram
        const totalRamBytes = (parseBytes(r.otel.ram) * r.otel.replicas) +
            (parseBytes(r.router.ram) * r.router.replicas) +
            (parseBytes(r.ingestor.ram) * r.ingestor.replicas) +
            (parseBytes(r.compactor.ram) * r.compactor.replicas) +
            (parseBytes(r.store.ram) * r.store.replicas) +
            (parseBytes(r.frontend.ram) * r.frontend.replicas) +
            (parseBytes(r.querier.ram) * r.querier.replicas);

        // Sum PVC
        // Note: Collector might have ephemeral (pvc mapped), but usually we track persistent storage here.
        // If otel has ephemeral, do we count it as PVC? UI says "PVC Storage (Local Disks)". 
        // Ephemeral is local disk. Let's include it if mapped.
        // Current logic: ingestor + compactor + store.

        const totalPvcBytes = (parseBytes(r.ingestor.pvc) * r.ingestor.replicas) +
            (parseBytes(r.compactor.pvc) * r.compactor.replicas) +
            (parseBytes(r.store.pvc) * r.store.replicas);

        document.getElementById('totalPods').innerText = totalPods;
        document.getElementById('totalCpu').innerText = totalCpu.toFixed(1) + " vCPU";
        document.getElementById('totalRam').innerText = formatBytes(totalRamBytes);
        document.getElementById('totalPvc').innerText = formatBytes(totalPvcBytes);
        document.getElementById('totalS3').innerText = r.S3Size;

        // Update UI Elements
        // OTel
        document.getElementById('otelReplicas').innerText = r.otel.replicas + " Replicas";
        document.getElementById('otelCpu').innerText = r.otel.cpu + " CPU";
        document.getElementById('otelRam').innerText = r.otel.ram;

        // Router
        document.getElementById('routerReplicas').innerText = r.router.replicas + " Replicas";
        document.getElementById('routerCpu').innerHTML = `${r.router.cpu} CPU <span class="per-pod">/ Pod</span>`;
        document.getElementById('routerRam').innerHTML = `${r.router.ram} <span class="per-pod">/ Pod</span>`;

        // Ingestor
        document.getElementById('ingestorShards').innerText = r.ingestor.replicas + " Pods";
        document.getElementById('thanosRam').innerHTML = `${r.ingestor.ram} <span class="per-pod">/ Pod</span>`;
        document.getElementById('thanosDisk').innerHTML = `${r.ingestor.pvc} <span class="per-pod">/ Pod</span>`;
        document.getElementById('thanosCpu').innerHTML = `${r.ingestor.cpu} CPU <span class="per-pod">/ Pod</span>`;

        // S3
        document.getElementById('s3Storage').innerText = r.S3Size;

        // Compactor
        document.getElementById('compactReplicas').innerText = r.compactor.replicas + " Replicas";
        document.getElementById('compactDisk').innerText = r.compactor.pvc;
        document.getElementById('compactRam').innerText = r.compactor.ram;
        document.getElementById('compactCpu').innerText = r.compactor.cpu + " CPU";

        // Store
        document.getElementById('storeReplicas').innerText = r.store.replicas + " Replicas";
        document.getElementById('storeRam').innerHTML = `${r.store.ram} <span class="per-pod">/ Pod</span>`;
        document.getElementById('storeCpu').innerHTML = `${r.store.cpu} CPU <span class="per-pod">/ Pod</span>`;
        document.getElementById('storePvc').innerHTML = `${r.store.pvc} <span class="per-pod">Total</span>`;

        // Frontend
        document.getElementById('frontendReplicas').innerText = r.frontend.replicas + " Replicas";
        document.getElementById('frontendCpuVal').innerHTML = `${r.frontend.cpu} CPU <span class="per-pod">/ Pod</span>`;
        document.getElementById('frontendRamVal').innerHTML = `${r.frontend.ram} <span class="per-pod">/ Pod</span>`;

        // Querier
        document.getElementById('querierReplicas').innerText = r.querier.replicas + " Replicas";
        document.getElementById('querierCpuVal').innerHTML = `${r.querier.cpu} CPU <span class="per-pod">/ Pod</span>`;
        document.getElementById('querierRamVal').innerHTML = `${r.querier.ram} <span class="per-pod">/ Pod</span>`;

        // Hide unused elements
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

copyToClipboard = copyToClipboard;
window.calculate = calculate;

