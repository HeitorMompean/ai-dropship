import os
path = '/app/app/routers/decisions.py'
with open(path, 'r') as f: content = f.read()
if 'create_decision' in content:
    print('ALREADY_EXISTS')
else:
    endpoint = "\n\n@router.post("""", response_model=schemas.DecisionOut, status_code=201)\nasync def create_decision(payload: schemas.DecisionCreate, db: AsyncSession = Depends(get_db)) -> Decision:\n    decision = Decision(agent_name=payload.agent_name, decision_type=payload.decision_type, context_json=payload.context_json, sms_text_sent=payload.sms_text_sent, timeout_at=payload.timeout_at, status='pending')\n    db.add(decision); await db.commit(); await db.refresh(decision)\n    try:\n        from app.services.telegram_service import telegram_service\n        await telegram_service.send_message(f'<b>New Decision #{decision.id}</b>\\nAgent: {decision.agent_name}\\nType: {decision.decision_type}\\n\\n{decision.sms_text_sent}\\n\\nReply YES to approve, NO to reject.')\n    except: pass\n    return decision\n\n"
    pos = content.find('@router.get')
    content = content[:pos] + endpoint + content[pos:]
    with open(path, 'w') as f: f.write(content)
    print('SUCCESS')
