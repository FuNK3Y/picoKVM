# The configuration page, at /config (password-protected)
content = r"""<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>picoKVM settings</title>
    <link rel="stylesheet" href="/style.css">
    <style>
        main {
            max-width: 640px;
            margin: 0 auto;
            padding: 16px;
        }

        h1 {
            font-size: 22px;
        }

        section {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 4px 16px 16px;
            margin-bottom: 16px;
        }

        h2 {
            font-size: 17px;
        }

        label {
            display: block;
            margin-top: 10px;
            font-size: 14px;
        }

        input:not([type=checkbox]):not([type=color]):not([type=range]),
        select,
        textarea {
            display: block;
            box-sizing: border-box;
            width: 100%;
            margin-top: 4px;
            padding: 7px;
            border: 1px solid var(--border);
            border-radius: 5px;
            background: var(--background);
            color: var(--text);
            font: inherit;
        }

        input[type=range] {
            display: block;
            width: 100%;
            margin: 8px 0 0;
        }

        textarea {
            font-family: monospace;
            min-height: 140px;
        }

        .row {
            display: flex;
            gap: 12px;
            align-items: flex-end;
        }

        .row>* {
            flex: 1;
        }

        .row>input[type=color] {
            flex: 0 0 48px;
            height: 36px;
            padding: 2px;
        }

        .monitor,
        .subsection {
            border-top: 1px solid var(--border);
            margin-top: 14px;
            padding-top: 4px;
        }

        button {
            margin-top: 12px;
            padding: 8px 14px;
            border: 1px solid var(--border);
            border-radius: 5px;
            background: var(--background);
            color: var(--text);
            font: inherit;
            cursor: pointer;
        }

        button.primary {
            background: var(--accent);
            border-color: var(--accent);
            color: white;
        }

        button:disabled {
            opacity: 0.6;
            cursor: default;
        }

        progress {
            width: 100%;
        }

        footer {
            position: sticky;
            bottom: 0;
            padding: 8px 0 12px;
            background: var(--background);
        }
    </style>
</head>

<body>
    <main>
        <p><a href="/">&larr; Back</a></p>
        <h1>Settings</h1>

        <section>
            <h2>Firmware</h2>
            <div id="version" class="muted">Loading...</div>
            <label>Update repository (GitHub)
                <input id="update_repository" placeholder="owner/name">
            </label>
            <button id="check" onclick="checkUpdate()">Check for updates</button>
            <button id="install" class="primary" hidden onclick="installLatest()"></button>
            <div id="update-message" class="muted"></div>
            <div class="subsection">
                <h3>Manual update</h3>
                <label>Firmware file (firmware-ota.bin)
                    <input id="file" type="file" accept=".bin">
                </label>
                <button onclick="upload()">Upload</button>
                <progress id="progress" max="1" value="0" hidden></progress>
                <div id="upload-message" class="muted"></div>
            </div>
        </section>

        <section>
            <h2>Wi-Fi</h2>
            <p class="muted">Changing these restarts the device. If it cannot join the network any more, set them again over USB.</p>
            <label>Network (SSID) <input id="ssid"></label>
            <label>Password <input id="wifi_password" type="password" placeholder="Unchanged"></label>
            <label>Hostname <input id="hostname"></label>
        </section>

        <section>
            <h2>Inputs</h2>
            <div class="row">
                <label>Input A name <input id="name_A"></label>
                <input id="color_A" type="color" title="Input A color">
            </div>
            <div class="row">
                <label>Input B name <input id="name_B"></label>
                <input id="color_B" type="color" title="Input B color">
            </div>
            <label>LED brightness when idle: <span id="brightness_value"></span>
                <input id="brightness" type="range" min="0" max="1" step="0.05" oninput="showBrightness()">
            </label>
        </section>

        <section>
            <h2>Monitors</h2>
            <div id="monitors"></div>
            <button onclick="addDdc()">Add a DDC/CI monitor</button>
            <button onclick="addOther()">Add another device (JSON)</button>
        </section>

        <section>
            <h2>Admin password</h2>
            <label>New password <input id="admin_password" type="password" placeholder="Unchanged" autocomplete="new-password"></label>
            <label>Confirm <input id="admin_password_confirm" type="password" autocomplete="new-password"></label>
        </section>

        <footer>
            <button id="save" class="primary" onclick="save()">Save</button>
            <span id="save-message" class="muted"></span>
        </footer>
    </main>

    <script>
        const $ = id => document.getElementById(id);
        let monitors = []; // {type, data}: data keeps the settings the form does not show

        function showBrightness() {
            $('brightness_value').innerText = Math.round($('brightness').value * 100) + '%';
        }

        function field(label, input) {
            const element = document.createElement('label');
            element.append(label, input);
            return element;
        }

        function numberInput(value, onchange) {
            const input = document.createElement('input');
            input.type = 'number';
            input.min = 0;
            input.max = 255;
            input.value = value;
            input.onchange = () => onchange(parseInt(input.value));
            return input;
        }

        function renderMonitors() {
            const container = $('monitors');
            container.replaceChildren();
            if (!monitors.length)
                container.append(Object.assign(document.createElement('p'), { className: 'muted', innerText: 'None: only the USB peripherals switch.' }));
            monitors.forEach((monitor, index) => {
                const box = document.createElement('div');
                box.className = 'monitor';
                const title = document.createElement('h3');
                title.innerText = monitor.type === 'DdcMonitor' ? 'DDC/CI monitor' : monitor.type;
                box.append(title);
                if (monitor.type === 'DdcMonitor') {
                    const data = monitor.data;
                    const port = document.createElement('select');
                    for (const hdmi of [1, 2])
                        port.append(new Option('HDMI ' + hdmi, hdmi, false, data.hdmi === hdmi));
                    port.onchange = () => data.hdmi = parseInt(port.value);
                    box.append(field('Port', port));
                    const values = document.createElement('div');
                    values.className = 'row';
                    for (const input of ['A', 'B'])
                        values.append(field($('name_' + input).value + ' (input ' + input + '): monitor input value',
                            numberInput(data.inputs[input], value => data.inputs[input] = value)));
                    box.append(values);
                    box.append(Object.assign(document.createElement('div'), { className: 'muted', innerText: 'VCP 0x60 values, commonly 15 DisplayPort 1, 16 DisplayPort 2, 17 HDMI 1, 18 HDMI 2.' }));
                    const powerOn = document.createElement('input');
                    powerOn.type = 'checkbox';
                    powerOn.checked = !!data.power_on;
                    powerOn.onchange = () => data.power_on = powerOn.checked;
                    const powerLabel = field(powerOn, ' Power the monitor on first');
                    box.append(powerLabel);
                } else {
                    const text = document.createElement('textarea');
                    text.value = JSON.stringify(monitor, null, 2);
                    text.onchange = () => {
                        try {
                            Object.assign(monitor, JSON.parse(text.value));
                            text.setCustomValidity('');
                        } catch (e) {
                            text.setCustomValidity('Invalid JSON');
                            text.reportValidity();
                        }
                    };
                    box.append(text);
                }
                const remove = document.createElement('button');
                remove.innerText = 'Remove';
                remove.onclick = () => {
                    monitors.splice(index, 1);
                    renderMonitors();
                };
                box.append(remove);
                container.append(box);
            });
        }

        function addDdc() {
            const used = monitors.filter(monitor => monitor.type === 'DdcMonitor').map(monitor => monitor.data.hdmi);
            monitors.push({ type: 'DdcMonitor', data: { hdmi: used.includes(1) ? 2 : 1, inputs: { A: 15, B: 17 }, power_on: false } });
            renderMonitors();
        }

        function addOther() {
            monitors.push({ type: 'GenericDevice', data: { uri: 'http://monitor/api', method: 'POST', kwargs: { A: { data: '' }, B: { data: '' } } } });
            renderMonitors();
        }

        async function load() {
            const response = await fetch('/api/config');
            const settings = await response.json();
            if (!response.ok) {
                $('save-message').innerText = settings.message;
                $('save').disabled = true;
                return;
            }
            $('ssid').value = settings.wireless_network.SSID;
            $('hostname').value = settings.wireless_network.hostname;
            for (const input of ['A', 'B']) {
                $('name_' + input).value = settings.inputs[input].name;
                $('color_' + input).value = settings.inputs[input].color.toLowerCase();
            }
            $('brightness').value = settings.led_idle_brightness;
            showBrightness();
            $('update_repository').value = settings.update_repository;
            monitors = settings.devices;
            renderMonitors();
        }

        async function save() {
            const message = $('save-message');
            if ($('admin_password').value !== $('admin_password_confirm').value) {
                message.innerText = 'The admin passwords differ';
                return;
            }
            const settings = {
                wireless_network: { SSID: $('ssid').value, hostname: $('hostname').value, password: $('wifi_password').value },
                inputs: {
                    A: { name: $('name_A').value, color: $('color_A').value },
                    B: { name: $('name_B').value, color: $('color_B').value },
                },
                led_idle_brightness: parseFloat($('brightness').value),
                update_repository: $('update_repository').value,
                admin_password: $('admin_password').value,
                devices: monitors,
            };
            $('save').disabled = true;
            message.innerText = 'Saving...';
            try {
                const response = await fetch('/api/config', { method: 'POST', body: JSON.stringify(settings) });
                const data = await response.json();
                message.innerText = data.message;
                if (response.ok && data.restart) {
                    const host = settings.wireless_network.hostname;
                    message.innerText = 'Saved. Restarting: the device will be back at http://' + host + '.local';
                    return;
                }
                if (response.ok) {
                    $('wifi_password').value = $('admin_password').value = $('admin_password_confirm').value = '';
                    renderMonitors(); // The input names in the monitors' labels
                }
            } catch (e) {
                message.innerText = 'Not saved: ' + e.message;
            }
            $('save').disabled = false;
        }

        async function showVersion() {
            const response = await fetch('/api/update', { signal: AbortSignal.timeout(3000) }); // The device may be restarting
            const data = await response.json();
            $('version').innerText = 'Running ' + data.version + (data.status ? ' (' + data.status + ')' : '');
            return data.version;
        }

        // The repository in the field, saved or not
        function latestUrl() {
            return '/api/update/latest?repository=' + $('update_repository').value.trim();
        }

        async function checkUpdate() {
            $('check').disabled = true;
            $('update-message').innerText = 'Checking...';
            try {
                const response = await fetch(latestUrl());
                const data = await response.json();
                if (!response.ok)
                    throw new Error(data.message);
                $('update-message').innerText = data.update_available ? '' : 'Up to date (' + data.latest + ')';
                $('install').hidden = !data.update_available;
                $('install').innerText = 'Install ' + data.latest;
            } catch (e) {
                $('update-message').innerText = 'Check failed: ' + e.message;
            }
            $('check').disabled = false;
        }

        // After an update: the device restarts into it, then confirms it once back on the network
        async function waitForRestart(message) {
            message.innerText = 'Restarting...';
            await new Promise(resolve => setTimeout(resolve, 5000));
            for (let attempt = 0; attempt < 60; attempt++) {
                try {
                    await showVersion();
                    message.innerText = '';
                    return;
                } catch (e) {
                    await new Promise(resolve => setTimeout(resolve, 3000));
                }
            }
            message.innerText = 'The device did not come back: check it over USB';
        }

        async function installLatest() {
            $('install').disabled = true;
            $('update-message').innerText = 'Downloading and installing (about a minute)...';
            try {
                const response = await fetch(latestUrl(), { method: 'POST' });
                const data = await response.json();
                if (!response.ok)
                    throw new Error(data.message);
                $('install').hidden = true;
                await waitForRestart($('update-message'));
            } catch (e) {
                $('update-message').innerText = 'Update failed: ' + e.message;
            }
            $('install').disabled = false;
        }

        function upload() {
            const file = $('file').files[0];
            if (!file) {
                $('upload-message').innerText = 'Choose firmware-ota.bin first';
                return;
            }
            const request = new XMLHttpRequest(); // Unlike fetch, it reports the upload's progress
            request.open('POST', '/api/update');
            request.upload.onprogress = event => $('progress').value = event.loaded / event.total;
            request.onload = async () => {
                $('progress').hidden = true;
                const data = JSON.parse(request.responseText);
                if (request.status !== 200)
                    $('upload-message').innerText = 'Update failed: ' + data.message;
                else
                    await waitForRestart($('upload-message'));
            };
            request.onerror = () => {
                $('progress').hidden = true;
                $('upload-message').innerText = 'Upload failed';
            };
            $('progress').hidden = false;
            $('upload-message').innerText = 'Uploading ' + file.name + '...';
            request.send(file);
        }

        window.onload = () => {
            load();
            showVersion();
        };
    </script>
</body>

</html>"""
