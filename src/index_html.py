# The web page (frozen code cannot open files: it is a module rather than index.html)
content = r"""<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{hostname}}</title>
    <link rel="stylesheet" href="/style.css">
    <style>
        body {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
        }

        .button-container {
            text-align: center;
        }

        .firmware {
            margin-top: 20px;
        }

        .api-button.switching {
            animation: pulse 0.4s infinite alternate;
        }

        @keyframes pulse {
            to {
                opacity: 0.4;
            }
        }

        .api-button {
            padding: 20px 40px;
            font-size: 20px;
            cursor: pointer;
            border: none;
            background-color: var(--accent);
            color: white;
            border-radius: 5px;
        }
    </style>
    <script>
        function show(state) {
            const [input, settings] = Object.entries(state.switching || state.active_input)[0];
            const button = document.querySelector('.api-button');
            button.innerText = (state.switching ? 'Switching to ' : 'Active input: ') + settings.name;
            button.style.backgroundColor = settings.color;
            button.classList.toggle('switching', !!state.switching);
            document.querySelector('#error').innerText = state.error ? 'Switch failed: ' + state.error : '';
        }

        // The state comes from the device as it changes, whoever switches (this page, another one, the button)
        function listen() {
            const events = new EventSource('/api/events');
            events.onmessage = event => show(JSON.parse(event.data));
            events.onerror = () => {
                document.querySelector('.api-button').innerText = 'Reconnecting...';
                if (events.readyState === EventSource.CLOSED) // Refused (too many open pages): the browser gives up
                    setTimeout(listen, 5000);
            };
        }

        async function toggle() {
            const response = await fetch('/api/active_input/', { method: 'POST' });
            const data = await response.json();
            if (response.ok)
                show(data);
            else
                document.querySelector('#error').innerText = 'Switch failed: ' + data.message;
        }

        async function showVersion() {
            const response = await fetch('/api/update', { signal: AbortSignal.timeout(3000) }); // The device may be restarting
            const data = await response.json();
            document.querySelector('#version').innerText = 'Firmware ' + data.version + (data.status ? ' (' + data.status + ')' : '');
        }

        let latest = null;

        // First click: check for an update. Second click: install it (the browser asks for the admin password)
        async function update() {
            const button = document.querySelector('#update-button');
            button.disabled = true;
            try {
                if (!latest) {
                    button.innerText = 'Checking...';
                    const response = await fetch('/api/update/latest');
                    const data = await response.json();
                    if (!response.ok)
                        throw new Error(data.message);
                    if (!data.update_available) {
                        button.innerText = 'Up to date';
                        return;
                    }
                    latest = data.latest;
                    button.innerText = 'Update to ' + latest;
                    button.disabled = false;
                    return;
                }
                button.innerText = 'Updating to ' + latest + '...';
                const response = await fetch('/api/update/latest', { method: 'POST' });
                const data = await response.json();
                if (!response.ok)
                    throw new Error(data.message);
                button.innerText = 'Restarting...';
                await new Promise(resolve => setTimeout(resolve, 5000));
                for (let attempt = 0; attempt < 60; attempt++) { // Up to the end of the update's trial boot
                    try {
                        await showVersion();
                        button.innerText = 'Check for updates';
                        latest = null;
                        button.disabled = false;
                        return;
                    } catch (e) {
                        await new Promise(resolve => setTimeout(resolve, 3000));
                    }
                }
                throw new Error('the device did not come back');
            } catch (e) {
                latest = null;
                button.innerText = 'Update failed: ' + e.message;
                button.disabled = false;
            }
        }

        window.onload = () => {
            listen();
            showVersion();
        };
    </script>
</head>

<body>
    <div class="button-container">
        <button class="api-button" onclick="toggle()">Loading...</button>
        <div id="error" class="error"></div>
        <div class="firmware muted">
            <span id="version"></span>
            <button id="update-button" class="link-button" onclick="update()">Check for updates</button>
        </div>
    </div>
</body>

</html>"""
