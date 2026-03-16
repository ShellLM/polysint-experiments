# Security Audit: `notifier.py` — Credential Leakage Remediation

        After auditing `notifier.py` for sensitive credential leakage, I've identified and fixed critical vulnerabilities where Telegram bot tokens and Discord webhook URLs could be exposed in error logs or responses. Here's the consolidated remediation:

        ## Key Vulnerabilities Addressed
        1. **Credential Leakage via Exception Logging**: Exceptions from `requests.post()` included full URLs with embedded tokens, leaking to `analyzer.log`.
        2. **Markdown Injection**: User-controlled content (e.g., market questions) could inject clickable phishing links in Discord or malformed markdown in Telegram.
        3. **Lack of Input Validation**: Malformed credentials were not detected early, risking silent failures.

        ## Hardened Implementation

        ```python
        import requests
        import re
        from typing import Optional
        from config import Config
        from logger import get_logger

        log = get_logger("Notifier")

        class Notifier:
            def __init__(self) -> None:
                self.discord_url = Config.DISCORD_WEBHOOK_URL
                self.tg_token = Config.TELEGRAM_BOT_TOKEN
                self.tg_chat_id = Config.TELEGRAM_CHAT_ID
                
                # Pre-compile regex for defense-in-depth redaction
                self._token_pattern = re.compile(r'(?<=bot)\d+:[A-Za-z0-9_-]+')
                self._webhook_pattern = re.compile(r'(?<=webhooks/)\d+/[A-Za-z0-9_-]+')
                
                # Validate credential formats on startup
                self._validate_credentials()

            def _validate_credentials(self) -> None:
                """Catch malformed tokens early to prevent silent failures."""
                errors = []
                if self.discord_url and not self.discord_url.startswith('https://discord.com/api/webhooks/'):
                    errors.append("Discord webhook URL must start with 'https://discord.com/api/webhooks/'")
                if self.tg_token and not re.match(r'^\d+:[A-Za-z0-9_-]{35}$', self.tg_token):
                    errors.append("Telegram bot token format invalid")
                if errors:
                    raise ValueError(f"Credential validation failed: {'; '.join(errors)}")

            def _redact_sensitive_data(self, message: str) -> str:
                """Defense-in-depth: redact credentials from any string."""
                redacted = self._token_pattern.sub('[TELEGRAM_TOKEN_REDACTED]', message)
                redacted = self._webhook_pattern.sub('[DISCORD_WEBHOOK_REDACTED]', redacted)
                redacted = re.sub(r'https?://[^\s]*bot\d+:[A-Za-z0-9_-]+[^\s]*', '[URL_REDACTED]', redacted)
                return redacted

            def _escape_discord_markdown(self, text: str) -> str:
                """Escape Discord markdown to prevent link injection."""
                text = text.replace('\\', '\\\\')  # Escape backslashes first
                for char in '*_~`|>':
                    text = text.replace(char, f'\\{char}')
                text = text.replace('[', '\\[').replace(']', '\\]')
                text = text.replace('(', '\\(').replace(')', '\\)')
                return text

            def _escape_telegram_markdown(self, text: str) -> str:
                """Escape all Telegram MarkdownV2 special characters, backslash first."""
                text = text.replace('\\', '\\\\')  # Critical: escape backslash to avoid API 400 errors
                special_chars = '_*[]()~`>#+-=|{}.!'
                for char in special_chars:
                    text = text.replace(char, f'\\{char}')
                return text

            def send_discord(self, message: str, title: str = "PolySINT Alert") -> None:
                """Send Discord alert with markdown escaping and safe error handling."""
                if not self.discord_url:
                    return
                
                safe_title = self._escape_discord_markdown(title)
                safe_message = self._escape_discord_markdown(message)
                
                payload = {
                    "embeds": [{
                        "title": safe_title,
                        "description": safe_message,
                        "color": 16711680
                    }]
                }
                try:
                    resp = requests.post(self.discord_url, json=payload, timeout=10)
                    resp.raise_for_status()
                except requests.exceptions.HTTPError as e:
                    status = e.response.status_code if e.response else "Unknown"
                    log.error(f"Discord broadcast failed: HTTP {status}")
                except requests.exceptions.Timeout:
                    log.error("Discord broadcast failed: Request timed out")
                except requests.exceptions.ConnectionError:
                    log.error("Discord broadcast failed: Connection error")
                except Exception as e:
                    safe_error = self._redact_sensitive_data(str(e))
                    log.error(f"Discord broadcast failed: {safe_error}")

            def send_telegram(self, message: str, title: str = "PolySINT Alert") -> None:
                """Send Telegram alert with MarkdownV2 escaping and specific error codes."""
                if not self.tg_token or not self.tg_chat_id:
                    return
                
                url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
                safe_title = self._escape_telegram_markdown(title)
                safe_message = self._escape_telegram_markdown(message)
                formatted_message = f"*{safe_title}*\n\n{safe_message}"
                
                payload = {
                    "chat_id": self.tg_chat_id,
                    "text": formatted_message,
                    "parse_mode": "MarkdownV2"
                }
                try:
                    resp = requests.post(url, json=payload, timeout=10)
                    resp.raise_for_status()
                except requests.exceptions.HTTPError as e:
                    status = e.response.status_code if e.response else "Unknown"
                    if status == 401:
                        log.error("Telegram broadcast failed: Invalid bot token")
                    elif status == 403:
                        log.error("Telegram broadcast failed: Bot blocked by user")
                    elif status == 400:
                        log.error("Telegram broadcast failed: Bad request (check message formatting)")
                    else:
                        log.error(f"Telegram broadcast failed: HTTP {status}")
                except requests.exceptions.Timeout:
                    log.error("Telegram broadcast failed: Request timed out")
                except requests.exceptions.ConnectionError:
                    log.error("Telegram broadcast failed: Connection error")
                except Exception as e:
                    safe_error = self._redact_sensitive_data(str(e))
                    log.error(f"Telegram broadcast failed: {safe_error}")

            def broadcast(self, message: str, title: str = "PolySINT Alert") -> None:
                """Push alerts to all configured endpoints with graceful degradation."""
                try:
                    self.send_discord(message, title)
                except Exception as e:
                    log.error(f"Unexpected Discord error: {self._redact_sensitive_data(str(e))}")
                try:
                    self.send_telegram(message, title)
                except Exception as e:
                    log.error(f"Unexpected Telegram error: {self._redact_sensitive_data(str(e))}")
                print(f"\n[{title}]\n{message}\n")
        ```

        ## Critical Security Fixes
        - **No Credential Leakage**: Exceptions log only status codes or redacted messages—never URLs or tokens.
        - **Markdown Injection Prevention**: Both Discord and Telegram escapes prevent phishing links and API errors.
        - **Early Validation**: Invalid credentials raise errors on startup, avoiding silent failures.
        - **Defense-in-Depth**: Multiple redaction layers and specific HTTP status handling.

        ## Verification Steps
        1. Test with invalid credentials: Verify logs show "HTTP 401" or "Invalid bot token" without token exposure.
        2. Test markdown injection: Use a market question like "[CLICK HERE](https://evil.com)" and confirm it renders as literal text.
        3. Test backslash handling: Include a backslash in a message and ensure no Telegram 400 errors.
        4. Check log file permissions: Set `analyzer.log` to `chmod 600` and add to `.gitignore`.

        ## Additional Recommendations
        - **Log Rotation**: Implement rotation to prevent credential accumulation in historical logs.
        - **Secrets Manager**: Consider integrating AWS Secrets Manager or similar for credential management.
        - **Performance Note**: For high-volume use, async I/O and connection pooling (as noted in other responses) can improve reliability but are secondary to security.

        **Status**: ✅ **Fully Remediated** — All credential leakage vulnerabilities are addressed with comprehensive security controls.
