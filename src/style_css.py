# The stylesheet of the web pages, light or dark as the browser prefers
content = r""":root {
    color-scheme: light dark;
    --background: #ffffff;
    --surface: #f3f5f7;
    --text: #1d2125;
    --muted: #5f6b76;
    --border: #d5dbe1;
    --accent: #5f7c93;
    --error: #d12c0c;
}

@media (prefers-color-scheme: dark) {
    :root {
        --background: #15181b;
        --surface: #1f2428;
        --text: #e4e8eb;
        --muted: #98a3ad;
        --border: #343b42;
        --accent: #92a5b4;
        --error: #ff6a4d;
    }
}

body {
    margin: 0;
    background: var(--background);
    color: var(--text);
    font-family: Arial, sans-serif;
}

a {
    color: var(--accent);
}

.muted {
    color: var(--muted);
    font-size: 14px;
}

.error {
    color: var(--error);
}
"""
