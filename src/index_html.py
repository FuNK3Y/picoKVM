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
        async function activeInput(action = 'get') {
            const url = '/api/active_input/';
            const options = action === 'set' ? { method: 'POST' } : {};
            if (action === 'set')
                document.querySelector('#button-text').innerText = 'Switching...';
            const response = await fetch(url, options);
            const data = await response.json();

            if (response.ok) {
                const input = Object.keys(data.active_input)[0];
                document.querySelector('#button-text').innerText = 'Active input: ' + data.active_input[input].name;
                document.querySelector('.api-button').style.backgroundColor = data.active_input[input].color;
            } else {
                document.querySelector('#button-text').innerText = 'Error: ' + data.message;
                document.querySelector('.api-button').style.backgroundColor = 'var(--error)';
            }
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
            activeInput();
            showVersion();
        };
    </script>
</head>

<body>
    <div class="button-container">
        <button class="api-button" onclick="activeInput('set')">
            <span id="button-text">Loading...</span>
        </button>
        <div class="firmware muted">
            <span id="version"></span>
            <button id="update-button" class="link-button" onclick="update()">Check for updates</button>
        </div>
    </div>
</body>

</html>"""
