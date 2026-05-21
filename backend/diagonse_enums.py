"""
Run inside the container:
    docker cp C:/Users/mompe/Downloads/ai-dropship-store/backend/diagnose_enums.py backend:/app/
    docker exec backend python /app/diagnose_enums.py
"""
import asyncio
import sys
sys.path.insert(0, "/app")

async def main():
    print("=" * 60)
    print("  TELEGRAM WEBHOOK DIAGNOSTIC")
    print("=" * 60)

    print("\n[1] Checking imports...")
    try:
        from app.models import Decision, DecisionStatus
        print(f"  ✅ Decision model OK")
        print(f"  ✅ DecisionStatus enum OK")
    except Exception as e:
        print(f"  ❌ Import error: {e}")
        return

    print("\n[2] Valid enum values:")
    members = list(DecisionStatus)
    values = [m.value for m in members]
    for m in members:
        print(f"    • {m.name} = '{m.value}'")
    print(f"\n  VALID DB values: {values}")

    print("\n[3] Common mistakes check:")
    for bad in ["approved", "rejected", "APPROVED"]:
        ok = bad.lower() in values
        print(f"    '{bad}' → {'✅ VALID' if ok else '❌ INVALID — would crash!'}")

    print("\n[4] Correct mapping:")
    print("    APPROVE  → 'executed'")
    print("    REJECT   → 'cancelled'")
    print("    NEGOTIATE→ 'replied'")

    print("\n[5] Testing DB connection...")
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Decision).limit(1))
            d = result.scalar_one_or_none()
            if d:
                print(f"  ✅ DB OK. Sample: ID={d.id}, status='{d.status}'")
            else:
                print("  ✅ DB OK. No decisions yet.")
    except Exception as e:
        print(f"  ❌ DB error: {e}")

    print("\n" + "=" * 60)
    print("  Done!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())