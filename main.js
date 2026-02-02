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

        // Summing (CPU * Replicas) because API now returns Per-Pod CPU
        const totalCpu = (r.otel.cpu * r.otel.replicas) +
            (r.router.cpu * r.router.replicas) +
            (r.ingestor.cpu * r.ingestor.replicas) +
            (r.compactor.cpu * r.compactor.replicas) +
            (r.store.cpu * r.store.replicas) +
            (r.frontend.cpu * r.frontend.replicas) +
            (r.querier.cpu * r.querier.replicas);


        // Helper to parse "X GB" or "X MB" back to bytes
        function parseBytes(str) {
            if (!str || str === "0 Bytes") return 0;
            const parts = str.split(' ');
            const val = parseFloat(parts[0]);
            const unit = parts[1];
            let multiplier = 1;
            if (unit === 'KB') multiplier = 1024;
            if (unit === 'MB') multiplier = 1024 * 1024;
            if (unit === 'GB') multiplier = 1024 * 1024 * 1024;
            if (unit === 'TB') multiplier = 1024 * 1024 * 1024 * 1024;
            return val * multiplier;
        }

        // Sum Totals
        const totalRamBytes = (parseBytes(r.otel.ram) * r.otel.replicas) +
            (parseBytes(r.router.ram) * r.router.replicas) +
            (parseBytes(r.ingestor.ram) * r.ingestor.replicas) +
            (parseBytes(r.compactor.ram) * r.compactor.replicas) +
            (parseBytes(r.store.ram) * r.store.replicas) +
            (parseBytes(r.frontend.ram) * r.frontend.replicas) +
            (parseBytes(r.querier.ram) * r.querier.replicas);

        const totalPvcBytes = (parseBytes(r.ingestor.pvc) * r.ingestor.replicas) +
            (parseBytes(r.compactor.pvc) * r.compactor.replicas) +
            (parseBytes(r.store.pvc) * r.store.replicas); // Store PVC is Total in UI, but API returns total? No, main.js label says Total. Let's check main.py. 
        // Main.py: store_pvc_total = ... -> returned as pvc. So r.store.pvc IS total.
        // Wait, I changed labels to "Per Pod" in index.html recently?
        // Let's re-verify Store PVC first. 
        // Main.py: pvc=format_bytes(store_pvc_total) where store_pvc_total = per_replica * replicas.
        // Actually main.py Step 174: pvc=format_bytes(store_pvc_total). 
        // So for Store, the API returns the TOTAL cluster PVC (cache).
        // BUT in Step 175 (main.js) I set label to "Total".
        // BUT later I refactored to "Per Replica" generally.
        // Let's assume for Store, since Replicas=1 usually (but can scale), and cache is shared... 
        // Actually, Store Cache is local per pod.
        // Let's just treat r.store.pvc as "Total" for now if replicas=1.
        // Correct logic: parseBytes(r.ingestor.pvc/pod) * replicas + parseBytes(r.compactor.pvc/pod)*replicas + parseBytes(r.store.pvc) (API returns Total for store).

        // Actually in main.py Step 174: `pvc=format_bytes(store_pvc_total)`
        // So r.store.pvc IS the sum of all store pods.
        // r.ingestor.pvc IS per pod (Step 163).
        // r.compactor.pvc IS per pod (Step 163 - although replicas always 1).

        // Let's fix the Summation Logic based on current API:
        // Ingestor: Per Pod (Replicas > 1) -> Multiply
        // Compactor: Per Pod (Replicas = 1) -> Multiply
        // Store: Total (Replicas >= 1) -> Don't Multiply (API gives total)

        // Wait, inconsistency! I should probably fix main.py to return Store PVC per Pod to be consistent. 
        // But for now, let's just implement the sum correctly based on current return values.

        let calculatedPvcBytes = (parseBytes(r.ingestor.pvc) * r.ingestor.replicas) +
            (parseBytes(r.compactor.pvc)) +
            (parseBytes(r.store.pvc));


        document.getElementById('totalPods').innerText = totalPods;
        document.getElementById('totalCpu').innerText = totalCpu.toFixed(1) + " vCPU";
        document.getElementById('totalRam').innerText = formatBytes(totalRamBytes);
        document.getElementById('totalPvc').innerText = formatBytes(calculatedPvcBytes);
        document.getElementById('totalS3').innerText = r.S3Size;

        // Update UI
        // OTel
        document.getElementById('otelReplicas').innerText = r.otel.replicas + " Replicas";
        document.getElementById('otelCpu').innerText = (r.otel.cpu < 1 ? 1 : r.otel.cpu) + " vCPU";
        document.getElementById('otelRam').innerText = r.otel.ram;

        // Router
        document.getElementById('routerReplicas').innerText = r.router.replicas + " Replicas";
        document.getElementById('routerCpu').innerHTML = `${r.router.cpu} vCPU <span class="per-pod">/ Pod</span>`;
        document.getElementById('routerRam').innerHTML = `${r.router.ram} <span class="per-pod">/ Pod</span>`;

        // Ingestor
        document.getElementById('ingestorShards').innerText = r.ingestor.replicas + " Pods";
        document.getElementById('thanosRam').innerHTML = `${r.ingestor.ram} <span class="per-pod">/ Pod</span>`;
        document.getElementById('thanosDisk').innerHTML = `${r.ingestor.pvc} <span class="per-pod">/ Pod</span>`;
        document.getElementById('thanosCpu').innerHTML = `${r.ingestor.cpu.toFixed(1)} vCPU <span class="per-pod">/ Pod</span>`;

        // S3
        document.getElementById('s3Storage').innerText = r.S3Size;
        document.getElementById('s3Raw').innerText = r.S3Raw;
        document.getElementById('s35m').innerText = r.S35m;
        document.getElementById('s31h').innerText = r.S31h;

        // Compactor
        document.getElementById('compactReplicas').innerText = r.compactor.replicas + " Replicas";
        document.getElementById('compactDisk').innerText = r.compactor.pvc;
        document.getElementById('compactRam').innerText = r.compactor.ram;
        document.getElementById('compactCpu').innerText = r.compactor.cpu + " vCPU";

        // Store
        document.getElementById('storeReplicas').innerText = r.store.replicas + " Replicas";
        document.getElementById('storeRam').innerHTML = `${r.store.ram} <span class="per-pod">/ Pod</span>`;
        document.getElementById('storeCpu').innerHTML = `${r.store.cpu} vCPU <span class="per-pod">/ Pod</span>`;
        document.getElementById('storePvc').innerHTML = `${r.store.pvc} <span class="per-pod">Total</span>`;

        // Frontend
        document.getElementById('frontendReplicas').innerText = r.frontend.replicas + " Replicas";
        document.getElementById('frontendCpuVal').innerHTML = `${r.frontend.cpu} vCPU <span class="per-pod">/ Pod</span>`;
        document.getElementById('frontendRamVal').innerHTML = `${r.frontend.ram} <span class="per-pod">/ Pod</span>`;

        // Querier
        document.getElementById('querierReplicas').innerText = r.querier.replicas + " Replicas";
        document.getElementById('querierCpuVal').innerHTML = `${r.querier.cpu} vCPU <span class="per-pod">/ Pod</span>`;
        document.getElementById('querierRamVal').innerHTML = `${r.querier.ram} <span class="per-pod">/ Pod</span>`;

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

