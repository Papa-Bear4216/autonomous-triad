import json
from pathlib import Path

cases = [
    {
        "id": "case_001",
        "diff": """--- a/src/api/pagination.py
+++ b/src/api/pagination.py
@@ -10,6 +10,6 @@ def get_paginated_records(db, page: int, page_size: int):
-    offset = (page - 1) * page_size
+    offset = page * page_size
     return db.query(Record).offset(offset).limit(page_size).all()""",
        "bug_description": "off-by-one in pagination offset calculation",
        "expected_catch": True,
        "keywords": ["off-by-one", "pagination", "offset", "page - 1", "page 0", "skip"]
    },
    {
        "id": "case_002",
        "diff": """--- a/src/services/userService.ts
+++ b/src/services/userService.ts
@@ -14,7 +14,7 @@ export async function updateUserPreferences(userId: string, prefs: Preferences) {
     const sanitized = validate(prefs);
-    await auditLogRepository.record(userId, "PREF_UPDATE");
+    auditLogRepository.record(userId, "PREF_UPDATE");
     return db.users.update(userId, sanitized);
 }""",
        "bug_description": "unawaited async operation / missing await on auditLogRepository.record",
        "expected_catch": True,
        "keywords": ["await", "unawaited", "promise", "async", "floating promise", "race condition"]
    },
    {
        "id": "case_003",
        "diff": """--- a/src/utils/file_parser.py
+++ b/src/utils/file_parser.py
@@ -5,6 +5,6 @@ def parse_config(filepath: str) -> dict:
-    with open(filepath, 'r') as f:
-        return json.load(f)
+    f = open(filepath, 'r')
+    data = json.load(f)
+    return data""",
        "bug_description": "resource leak unclosed file handle without context manager",
        "expected_catch": True,
        "keywords": ["leak", "close", "context manager", "with open", "unclosed", "file descriptor"]
    },
    {
        "id": "case_004",
        "diff": """--- a/src/db/users.py
+++ b/src/db/users.py
@@ -8,5 +8,5 @@ def find_user_by_email(cursor, email: str):
-    cursor.execute("SELECT id, email, role FROM users WHERE email = %s", (email,))
+    cursor.execute(f"SELECT id, email, role FROM users WHERE email = '{email}'")
     return cursor.fetchone()""",
        "bug_description": "sql injection via string interpolation without parameterized query",
        "expected_catch": True,
        "keywords": ["sql injection", "injection", "parameterized", "sanitize", "sqli", "prepared statement"]
    },
    {
        "id": "case_005",
        "diff": """--- a/src/components/NotificationCounter.tsx
+++ b/src/components/NotificationCounter.tsx
@@ -12,5 +12,5 @@ export function NotificationCounter({ pollInterval }: Props) {
     useEffect(() => {
         const interval = setInterval(() => {
             fetchUnreadCount(lastSeenId);
-        }, pollInterval);
-    }, [pollInterval, lastSeenId]);
+        }, pollInterval);
+    }, [pollInterval]);""",
        "bug_description": "stale closure missing lastSeenId dependency in useEffect hook",
        "expected_catch": True,
        "keywords": ["stale closure", "dependency", "lastSeenId", "useeffect", "dependency array", "missing"]
    },
    {
        "id": "case_006",
        "diff": """--- a/src/routes/invoices.ts
+++ b/src/routes/invoices.ts
@@ -20,6 +20,6 @@ router.delete("/api/invoices/:id", async (req: AuthRequest, res: Response) => {
     const { id } = req.params;
-    const invoice = await db.invoices.findOne({ id, ownerId: req.user.id });
+    const invoice = await db.invoices.findOne({ id });
     if (!invoice) return res.status(404).json({ error: "Not found" });
     await db.invoices.delete(id);
     return res.status(204).send();
 });""",
        "bug_description": "insecure direct object reference IDOR missing ownership check",
        "expected_catch": True,
        "keywords": ["idor", "authorization", "owner", "ownerid", "permission", "access control", "unauthorized"]
    },
    {
        "id": "case_007",
        "diff": """--- a/src/utils/formatters.ts
+++ b/src/utils/formatters.ts
@@ -8,5 +8,5 @@ interface UserProfile {
 export function getDisplayTheme(profile?: UserProfile): string {
-    return profile?.settings?.theme?.toLowerCase() ?? "system";
+    return profile.settings.theme.toLowerCase();
 }""",
        "bug_description": "null pointer / undefined property access on optional profile",
        "expected_catch": True,
        "keywords": ["undefined", "null", "typeerror", "optional chaining", "null pointer", "cannot read property"]
    },
    {
        "id": "case_008",
        "diff": """--- a/src/models/cart.py
+++ b/src/models/cart.py
@@ -4,6 +4,6 @@ class CartItem:
-def create_cart_session(user_id: str, initial_items: list = None):
-    if initial_items is None:
-        initial_items = []
+def create_cart_session(user_id: str, initial_items: list = []):
     return {"user_id": user_id, "items": initial_items}""",
        "bug_description": "mutable default argument retaining mutated state across function calls",
        "expected_catch": True,
        "keywords": ["mutable default", "default argument", "mutable", "shared across calls", "list = []"]
    },
    {
        "id": "case_009",
        "diff": """--- a/src/workers/payment_processor.ts
+++ b/src/workers/payment_processor.ts
@@ -25,7 +25,7 @@ export async function processStripeEvent(event: StripeEvent) {
     try {
         await handlePaymentSettlement(event);
     } catch (err) {
-        logger.error("Payment settlement failed", { error: err, eventId: event.id });
-        throw err;
+        // Ignored
     }
 }""",
        "bug_description": "swallowed error in catch block silently ignoring payment failure",
        "expected_catch": True,
        "keywords": ["swallow", "silent", "ignored", "error handling", "empty catch", "suppress"]
    },
    {
        "id": "case_010",
        "diff": """--- a/src/auth/tokens.py
+++ b/src/auth/tokens.py
@@ -12,5 +12,5 @@ def is_token_expired(expires_at_utc: datetime) -> bool:
     # expires_at_utc has tzinfo=timezone.utc
-    now_utc = datetime.now(timezone.utc)
-    return now_utc >= expires_at_utc
+    now_local = datetime.now()
+    return now_local >= expires_at_utc""",
        "bug_description": "naive vs aware timezone comparison TypeError or offset mismatch",
        "expected_catch": True,
        "keywords": ["timezone", "naive", "aware", "utc", "datetime", "tzinfo", "offset"]
    },
    {
        "id": "case_011",
        "diff": """--- a/src/metrics/calculator.py
+++ b/src/metrics/calculator.py
@@ -15,6 +15,6 @@ def calculate_conversion_rate(successes: int, total_attempts: int) -> float:
-    if total_attempts <= 0:
-        return 0.0
     return (successes / total_attempts) * 100.0""",
        "bug_description": "division by zero error when total_attempts is 0",
        "expected_catch": True,
        "keywords": ["division by zero", "zerodivisionerror", "zero", "total_attempts", "denominator"]
    },
    {
        "id": "case_012",
        "diff": """--- a/src/finance/balances.py
+++ b/src/finance/balances.py
@@ -18,6 +18,6 @@ def verify_account_reconciliation(credits: float, debits: float, fee: float) ->
     total = credits - debits
-    return math.isclose(total, fee, abs_tol=1e-5)
+    return total == fee""",
        "bug_description": "strict equality comparison on floating point values instead of tolerance",
        "expected_catch": True,
        "keywords": ["float", "floating point", "precision", "equality", "isclose", "rounding", "epsilon"]
    }
]

out_dir = Path(__file__).resolve().parent.parent / "triad" / "bench" / "cases"
out_dir.mkdir(parents=True, exist_ok=True)

for c in cases:
    p = out_dir / f"{c['id']}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)
print(f"Wrote {len(cases)} test cases to {out_dir}")
