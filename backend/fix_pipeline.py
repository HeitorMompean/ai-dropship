import re
with open('/app/app/routers/telegram_webhook.py','r') as f: w=f.read()

# Fix 1: Add chat_id parameter
w=w.replace('async def _trigger_storekeeper_and_ad(decision: Decision, db: AsyncSession) -> str:',
            'async def _trigger_storekeeper_and_ad(decision: Decision, db: AsyncSession, chat_id: int = None) -> str:')

# Fix 2: Fix AI call
w=w.replace('ai_result = await telegram_ai_engine.process_message(ad_prompt)',
            'ai_result = await telegram_ai_engine.process_message(decision_id=f"ad_{decision.id}", user_message=ad_prompt, product_context=ctx)')

# Fix 3: Fix send_message chat_id references
w=w.replace('chat_id=decision.telegram_chat_id,', 'chat_id=chat_id,')

# Fix 4: Pass chat_id to pipeline
w=w.replace('pipeline_msg = await _trigger_storekeeper_and_ad(decision, db)',
            'pipeline_msg = await _trigger_storekeeper_and_ad(decision, db, chat_id=chat_id)')

with open('/app/app/routers/telegram_webhook.py','w') as f: f.write(w)
print('Fixed webhook')

# Fix 5: Fix send_message in telegram_service.py
with open('/app/app/services/telegram_service.py','r') as f: s=f.read()
s=s.replace('chat_id: Optional[str] = None,', 'chat_id = None,')
s=s.replace('if not self._token or not self._chat_id:', 'if not self._token:')
old_target = 'self._chat_id'
new_target = 'chat_id if chat_id else self._chat_id'
s=s.replace('"chat_id": self._chat_id,', '"chat_id": target_chat,')
s=s.replace('url = f"{self._base_url}/sendMessage"', 'url = self._base_url + "/sendMessage"')
with open('/app/app/services/telegram_service.py','w') as f: f.write(s)
print('Fixed telegram_service')
