I'll improve the wallet profiling results layout by creating a more structured, readable interface with clear sections and visual hierarchy.

```html
<!-- static/index.html - Updated profiling results section -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PolySINT — Intelligence Engine</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@300;400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0a0a0f;
            --surface: #12121a;
            --surface-hover: #1a1a25;
            --accent: #22d3ee;
            --accent-dim: rgba(34, 211, 238, 0.1);
            --warning: #f59e0b;
            --danger: #ef4444;
            --success: #10b981;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --border: #1e293b;
            --border-accent: rgba(34, 211, 238, 0.3);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background: var(--bg);
            color: var(--text-primary);
            font-family: 'Syne', sans-serif;
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at 20% 80%, rgba(34, 211, 238, 0.05) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(139, 92, 246, 0.03) 0%, transparent 50%);
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        .header {
            text-align: center;
            margin-bottom: 3rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border);
        }

        .title {
            font-size: 2.5rem;
            font-weight: 800;
            letter-spacing: -0.05em;
            margin-bottom: 0.5rem;
            background: linear-gradient(90deg, var(--accent), #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .subtitle {
            color: var(--text-secondary);
            font-family: 'DM Mono', monospace;
            font-size: 0.9rem;
            letter-spacing: 0.05em;
        }

        /* Profile Card */
        .profile-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 1rem;
            overflow: hidden;
            margin: 2rem 0;
            transition: all 0.3s ease;
        }

        .profile-card:hover {
            border-color: var(--border-accent);
            box-shadow: 0 0 30px rgba(34, 211, 238, 0.05);
        }

        .profile-header {
            background: linear-gradient(135deg, rgba(34, 211, 238, 0.1) 0%, rgba(139, 92, 246, 0.05) 100%);
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .profile-title {
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .profile-icon {
            width: 2.5rem;
            height: 2.5rem;
            background: rgba(34, 211, 238, 0.1);
            border-radius: 0.5rem;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
        }

        .profile-body {
            padding: 0;
        }

        /* Wallet Info Grid */
        .wallet-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1px;
            background: var(--border);
        }

        .wallet-cell {
            background: var(--surface);
            padding: 1.25rem 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .wallet-cell.header {
            background: rgba(15, 23, 42, 0.5);
            padding: 0.75rem 1.5rem;
            font-family: 'DM Mono', monospace;
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
            border-bottom: 1px solid var(--border);
        }

        .wallet-label {
            font-size: 0.8rem;
            color: var(--text-muted);
            font-family: 'DM Mono', monospace;
        }

        .wallet-value {
            font-size: 0.95rem;
            color: var(--text-primary);
            word-break: break-all;
        }

        .wallet-value.address {
            font-family: 'DM Mono', monospace;
            font-size: 0.85rem;
            color: var(--accent);
        }

        .wallet-value.eoa {
            font-family: 'DM Mono', monospace;
            font-size: 0.85rem;
            color: #a78bfa;
            background: rgba(167, 139, 250, 0.1);
            padding: 0.25rem 0.5rem;
            border-radius: 0.25rem;
            display: inline-block;
        }

        /* Profile Sections */
        .profile-sections {
            display: grid;
            gap: 1px;
            background: var(--border);
        }

        .profile-section {
            background: var(--surface);
            padding: 1.5rem 2rem;
        }

        .section-header {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 1.25rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border);
        }

        .section-icon {
            width: 2rem;
            height: 2rem;
            background: var(--accent-dim);
            border-radius: 0.375rem;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
        }

        .section-title {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-primary);
            letter-spacing: 0.02em;
        }

        .section-content {
            color: var(--text-secondary);
            line-height: 1.7;
            font-size: 0.9rem;
        }

        .section-content p {
            margin-bottom: 1rem;
        }

        .section-content p:last-child {
            margin-bottom: 0;
        }

        /* Highlight Boxes */
        .highlight-box {
            background: rgba(34, 211, 238, 0.05);
            border-left: 3px solid var(--accent);
            padding: 1rem 1.25rem;
            margin: 1rem 0;
            border-radius: 0 0.5rem 0.5rem 0;
        }

        .highlight-box.warning {
            background: rgba(245, 158, 11, 0.05);
            border-left-color: var(--warning);
        }

        .highlight-box.danger {
            background: rgba(239, 68, 68, 0.05);
            border-left-color: var(--danger);
        }

        .highlight-box.success {
            background: rgba(16, 185, 129, 0.05);
            border-left-color: var(--success);
        }

        /* Score Display */
        .score-display {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-top: 1.5rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border);
        }

        .score-circle {
            width: 4rem;
            height: 4rem;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            font-weight: 700;
            flex-shrink: 0;
        }

        .score-circle.high {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(239, 68, 68, 0.1));
            border: 2px solid var(--danger);
            color: var(--danger);
        }

        .score-circle.medium {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(245, 158, 11, 0.1));
            border: 2px solid var(--warning);
            color: var(--warning);
        }

        .score-circle.low {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.1));
            border: 2px solid var(--success);
            color: var(--success);
        }

        .score-details {
            flex: 1;
        }

        .score-label {
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-bottom: 0.25rem;
            font-family: 'DM Mono', monospace;
        }

        .score-justification {
            font-size: 0.9rem;
            color: var(--text-secondary);
            line-height: 1.5;
        }

        /* Loading State */
        .loading-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 4rem 2rem;
            gap: 1.5rem;
        }

        .loading-spinner {
            display: flex;
            gap: 0.5rem;
        }

        .spinner-dot {
            width: 0.75rem;
            height: 0.75rem;
            background: var(--accent);
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out both;
        }

        .spinner-dot:nth-child(1) { animation-delay: -0.32s; }
        .spinner-dot:nth-child(2) { animation-delay: -0.16s; }

        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }

        /* Error State */
        .error-container {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.2);
            border-radius: 0.75rem;
            padding: 2rem;
            text-align: center;
        }

        .error-icon {
            font-size: 2rem;
            margin-bottom: 1rem;
            opacity: 0.8;
        }

        .error-title {
            font-size: 1.1rem;
            color: var(--danger);
            margin-bottom: 0.5rem;
        }

        .error-message {
            color: var(--text-secondary);
            font-size: 0.9rem;
            max-width: 400px;
            margin: 0 auto;
        }

        /* Responsive */
        @media (max-width: 768px) {
            .container {
                padding: 1rem;
            }
            
            .wallet-grid {
                grid-template-columns: 1fr;
            }
            
            .profile-header {
                flex-direction: column;
                align-items: flex-start;
                gap: 1rem;
            }
        }
    </style>
</head>
<body>
    <!-- Existing HTML structure... -->
    
    <!-- Updated AI Modal Content -->
    <div id="aiModal" class="hidden fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
        <div class="bg-surface rounded-2xl border border-gray-800 max-w-4xl w-full max-h-[90vh] overflow-hidden">
            <div class="border-b border-gray-800 px-6 py-4 flex justify-between items-center">
                <h3 id="aiModalTitle" class="text-lg font-semibold text-white">🤖 Entity Profile</h3>
                <button onclick="closeModal()" class="text-gray-400 hover:text-white text-2xl leading-none">&times;</button>
            </div>
            <div id="aiModalContent" class="overflow-y-auto max-h-[calc(90vh-4rem)]">
                <!-- Dynamic content loaded here -->
            </div>
        </div>
    </div>

    <script>
        // Updated profileEntity function
        async function profileEntity(address, label) {
            const modal = document.getElementById('aiModal');
            const content = document.getElementById('aiModalContent');
            const modalTitle = document.getElementById('aiModalTitle');

            modal.classList.remove('hidden');
            modalTitle.innerHTML = `🧠 Entity Profile — ${label}`;

            // Loading state
            content.innerHTML = `
                <div class="loading-container">
                    <div class="loading-spinner">
                        <div class="spinner-dot"></div>
                        <div class="spinner-dot"></div>
                        <div class="spinner-dot"></div>
                    </div>
                    <div class="text-cyan-400 font-medium">Analyzing entity behavior...</div>
                    <div class="text-gray-500 text-sm max-w-xs text-center">
                        Fetching on-chain history, analyzing trade patterns, and generating intelligence profile.
                    </div>
                </div>`;

            try {
                const res = await fetch(`/wallets/${address}/profile`);
                if (!res.ok) throw new Error("Profiling Failed");
                const data = await res.json();

                // Parse the profile into sections
                const profile = data.profile;
                const sections = parseProfileSections(profile);

                // Build the enhanced layout
                let html = `
                    <div class="profile-card">
                        <div class="profile-header">
                            <div class="profile-title">
                                <div class="profile-icon">🎯</div>
                                <div>
                                    <div class="text-lg font-semibold">${label}</div>
                                    <div class="text-xs text-gray-400 font-mono mt-1">Entity Intelligence Profile</div>
                                </div>
                            </div>
                            <div class="text-xs text-gray-500 font-mono">
                                Generated: ${new Date().toLocaleTimeString()}
                            </div>
                        </div>
                        
                        <div class="profile-body">
                            <!-- Wallet Information Grid -->
                            <div class="wallet-grid">
                                <div class="wallet-cell header">WALLET IDENTIFIERS</div>
                                <div class="wallet-cell">
                                    <div class="wallet-label">Proxy Address (Polymarket)</div>
                                    <div class="wallet-value address">${address}</div>
                                </div>
                                <div class="wallet-cell">
                                    <div class="wallet-label">Real Owner (EOA)</div>
                                    <div class="wallet-value eoa">${data.real_owner}</div>
                                </div>
                            </div>
                            
                            <!-- Profile Sections -->
                            <div class="profile-sections">`;

                // Add each section with proper formatting
                if (sections.patterns) {
                    html += `
                        <div class="profile-section">
                            <div class="section-header">
                                <div class="section-icon">📊</div>
                                <div class="section-title">Trading Patterns</div>
                            </div>
                            <div class="section-content">
                                ${formatSectionContent(sections.patterns)}
                            </div>
                        </div>`;
                }

                if (sections.entityType) {
                    html += `
                        <div class="profile-section">
                            <div class="section-header">
                                <div class="section-icon">👤</div>
                                <div class="section-title">Entity Classification</div>
                            </div>
                            <div class="section-content">
                                <div class="highlight-box ${getEntityTypeClass(sections.entityType)}">
                                    <div class="font-semibold text-lg mb-2">${sections.entityType}</div>
                                    <div class="text-sm opacity-80">${getEntityDescription(sections.entityType)}</div>
                                </div>
                            </div>
                        </div>`;
                }

                if (sections.alphaLevel) {
                    const score = extractAlphaScore(sections.alphaLevel);
                    html += `
                        <div class="profile-section">
                            <div class="section-header">
                                <div class="section-icon">⚡</div>
                                <div class="section-title">Alpha Assessment</div>
                            </div>
                            <div class="section-content">
                                ${formatAlphaContent(sections.alphaLevel)}
                                ${score ? renderAlphaScore(score) : ''}
                            </div>
                        </div>`;
                }

                html += `
                            </div>
                        </div>
                    </div>`;

                content.innerHTML = html;

            } catch (e) {
                content.innerHTML = `
                    <div class="error-container">
                        <div class="error-icon">⚠️</div>
                        <div class="error-title">Profile Analysis Failed</div>
                        <div class="error-message">Could not generate entity profile. Check your connection and try again.</div>
                    </div>`;
            }
        }

        // Helper functions
        function parseProfileSections(profile) {
            const sections = {
                patterns: '',
                entityType: '',
                alphaLevel: ''
            };

            // Simple parsing - in production you'd want more robust parsing
            const patternsMatch = profile.match(/PATTERNS?:\s*([\s\S]*?)(?=ENTITY TYPE:|$)/i);
            const entityMatch = profile.match(/ENTITY TYPE:\s*([\s\S]*?)(?=ALPHA LEVEL:|$)/i);
            const alphaMatch = profile.match(/ALPHA LEVEL:\s*([\s\S]*?)$/i);

            if (patternsMatch) sections.patterns = patternsMatch[1].trim();
            if (entityMatch) sections.entityType = entityMatch[1].trim();
            if (alphaMatch) sections.alphaLevel = alphaMatch[1].trim();

            return sections;
        }

        function formatSectionContent(content) {
            if (!content) return '<p class="text-gray-500 italic">No pattern data available</p>';
            
            // Convert markdown-style formatting
            return content
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/\n/g, '<br>')
                .replace(/• /g, '→ ');
        }

        function getEntityTypeClass(type) {
            const lowerType = type.toLowerCase();
            if (lowerType.includes('whale') || lowerType.includes('quant')) return 'warning';
            if (lowerType.includes('bot') || lowerType.includes('maker')) return 'success';
            if (lowerType.includes('staffer') || lowerType.includes('expert')) return 'danger';
            return '';
        }

        function getEntityDescription(type) {
            const descriptions = {
                'whale': 'High-volume trader with significant market influence',
                'quantitative bot': 'Automated trading algorithm executing systematic strategies',
                'market maker': 'Provides liquidity and facilitates price discovery',
                'political staffer': 'Individual with potential insider political knowledge',
                'domain expert': 'Trader with specialized knowledge in specific markets',
                'retail speculator': 'Individual trader with limited market impact',
                'unknown': 'Insufficient data to determine entity type'
            };
            
            const lowerType = type.toLowerCase();
            for (const [key, desc] of Object.entries(descriptions)) {
                if (lowerType.includes(key)) return desc;
            }
            return 'Entity classification requires further analysis';
        }

        function extractAlphaScore(alphaText) {
            const match = alphaText.match(/(\d+)/);
            return match ? parseInt(match[1]) : null;
        }

        function formatAlphaContent(alphaText) {
            if (!alphaText) return '<p class="text-gray-500 italic">No alpha assessment available</p>';
            
            // Extract score and justification
            const parts = alphaText.split('—');
            const scorePart = parts[0];
            const justification = parts[1] || '';
            
            return `
                <div class="mb-4">
                    <div class="text-sm text-gray-400 mb-2">Assessment</div>
                    <div class="text-white">${scorePart}</div>
                </div>
                ${justification ? `
                <div class="text-sm text-gray-400 mb-2">Justification</div>
                <div class="text-gray-300">${justification.trim()}</div>
                ` : ''}
            `;
        }

        function renderAlphaScore(score) {
            let level = 'low';
            let label = 'Low Signal';
            let color = 'var(--success)';
            
            if (score >= 7) {
                level = 'high';
                label = 'High Signal';
                color = 'var(--danger)';
            } else if (score >= 4) {
                level = 'medium';
                label = 'Medium Signal';
                color = 'var(--warning)';
            }
            
            return `
                <div class="score-display">
                    <div class="score-circle ${level}">${score}</div>
                    <div class="score-details">
                        <div class="score-label">${label} (${score}/10)</div>
                        <div class="score-justification">
                            ${score >= 7 ? 'This entity demonstrates patterns consistent with significant information edge or market influence.' :
                              score >= 4 ? 'This entity shows moderate trading sophistication with some edge.' :
                              'This entity appears to trade with limited informational advantage.'}
                        </div>
                    </div>
                </div>
            `;
        }

        // Keep existing functions like closeModal, etc.
    </script>
</body>
</html>
```

## Key Improvements:

### 1. **Structured Layout**
- **Profile Header**: Clear entity title with timestamp
- **Wallet Grid**: Clean, tabular display of proxy and EOA addresses
- **Sectioned Content**: Organized into distinct sections with icons

### 2. **Visual Hierarchy**
- **Color-Coded Highlights**: Different colors for different entity types
- **Score Visualization**: Circular alpha score with color-coded levels
- **Section Icons**: Visual anchors for each analysis section

### 3. **Enhanced Readability**
- **Typography**: Better spacing, font weights, and line heights
- **Content Formatting**: Converted markdown-style bold to HTML, better paragraph spacing
- **Visual Separators**: Clear borders and section dividers

### 4. **Responsive Design**
- **Grid Layout**: Adapts from multi-column to single column on mobile
- **Flexible Spacing**: Maintains readability on all screen sizes

### 5. **Loading & Error States**
- **Animated Spinner**: Professional loading indicator
- **Error Handling**: Clear error messages with visual styling

### 6. **Interactive Elements**
- **Score Circles**: Visual representation of alpha scores
- **Highlight Boxes**: Contextual styling based on content type
- **Smooth Transitions**: Subtle hover effects and animations

The new layout transforms the raw text output into a professional intelligence report format, making it much easier to scan and understand the key findings about each entity.
