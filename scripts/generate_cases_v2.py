"""
Generates hardened benchmark test cases for autonomous-triad.
- Real-sized diffs (>40 lines) with bugs buried among normal changes.
- Negative controls (clean diffs with expected_catch: false).
- No keywords field (judge-based scoring).
"""

import json
from pathlib import Path

cases = [
    # -------------------------------------------------------------------------
    # Case 001: Pagination & Filtering API (Off-by-one offset)
    # -------------------------------------------------------------------------
    {
        "id": "case_001",
        "bug_description": "off-by-one error in pagination offset calculation (offset = page * page_size instead of (page - 1) * page_size)",
        "expected_catch": True,
        "diff": """--- a/src/api/items.py
+++ b/src/api/items.py
@@ -15,28 +15,35 @@ class ItemFilterParams:
     status: Optional[str] = "active"
     sort_by: Optional[str] = "created_at"
     sort_desc: Optional[bool] = True
+    min_price: Optional[float] = None
+    max_price: Optional[float] = None
 
-def list_catalog_items(db: Session, page: int = 1, page_size: int = 20):
-    query = db.query(CatalogItem).filter(CatalogItem.is_active == True)
-    total = query.count()
-    offset = (page - 1) * page_size
-    items = query.order_by(CatalogItem.created_at.desc()).offset(offset).limit(page_size).all()
-    return {"total": total, "page": page, "items": items}
+def list_catalog_items(db: Session, filter_params: ItemFilterParams, page: int = 1, page_size: int = 20):
+    query = db.query(CatalogItem)
+    if filter_params.status:
+        query = query.filter(CatalogItem.status == filter_params.status)
+    if filter_params.min_price is not None:
+        query = query.filter(CatalogItem.price >= filter_params.min_price)
+    if filter_params.max_price is not None:
+        query = query.filter(CatalogItem.price <= filter_params.max_price)
+
+    total = query.count()
+    # Apply sorting
+    sort_col = getattr(CatalogItem, filter_params.sort_by, CatalogItem.created_at)
+    if filter_params.sort_desc:
+        query = query.order_by(sort_col.desc())
+    else:
+        query = query.order_by(sort_col.asc())
+
+    # Calculate window
+    offset = page * page_size
+    items = query.offset(offset).limit(page_size).all()
+    total_pages = (total + page_size - 1) // page_size
+    return {
+        "total": total,
+        "page": page,
+        "page_size": page_size,
+        "total_pages": total_pages,
+        "items": [item.to_dict() for item in items]
+    }"""
    },

    # -------------------------------------------------------------------------
    # Case 002: User Profile Service (Unawaited Async Operation)
    # -------------------------------------------------------------------------
    {
        "id": "case_002",
        "bug_description": "missing await on auditLogger.recordSecurityEvent causing floating promise / unhandled async race condition",
        "expected_catch": True,
        "diff": """--- a/src/services/userProfileService.ts
+++ b/src/services/userProfileService.ts
@@ -20,22 +20,38 @@ export interface UpdateProfileDto {
     displayName?: string;
     locale?: string;
+    theme?: 'light' | 'dark' | 'system';
+    marketingOptIn?: boolean;
 }
 
 export class UserProfileService {
     constructor(
         private readonly userRepo: UserRepository,
-        private readonly notificationService: NotificationService
+        private readonly notificationService: NotificationService,
+        private readonly auditLogger: AuditLogger,
+        private readonly metrics: MetricsCollector
     ) {}
 
     async updateProfile(userId: string, dto: UpdateProfileDto): Promise<UserProfile> {
         const user = await this.userRepo.findById(userId);
         if (!user) {
             throw new NotFoundException(`User ${userId} not found`);
         }
 
+        const previousState = { ...user };
         if (dto.displayName !== undefined) {
             user.displayName = sanitizeName(dto.displayName);
         }
         if (dto.locale !== undefined) {
             user.locale = validateLocale(dto.locale);
         }
+        if (dto.theme !== undefined) {
+            user.theme = dto.theme;
+        }
+        if (dto.marketingOptIn !== undefined) {
+            user.marketingOptIn = dto.marketingOptIn;
+        }
+
+        user.updatedAt = new Date();
+        this.auditLogger.recordSecurityEvent(userId, 'PROFILE_UPDATED', { previous: previousState, updated: dto });
+        this.metrics.increment('user.profile.updates');
+        const saved = await this.userRepo.save(user);
+        return saved;
     }
 }"""
    },

    # -------------------------------------------------------------------------
    # Case 003: Export Utility (Resource Leak: Unclosed File Handle)
    # -------------------------------------------------------------------------
    {
        "id": "case_003",
        "bug_description": "resource leak from unclosed file descriptor f = open(...) without context manager or close call",
        "expected_catch": True,
        "diff": """--- a/src/reports/exporter.py
+++ b/src/reports/exporter.py
@@ -10,18 +10,32 @@ import csv
 import tempfile
 import gzip
 import shutil
+from typing import List, Dict, Any
 
-def export_transactions_csv(transactions: list, target_path: str) -> str:
-    with open(target_path, 'w', newline='', encoding='utf-8') as f:
-        writer = csv.writer(f)
-        writer.writerow(["id", "amount", "status", "timestamp"])
-        for tx in transactions:
-            writer.writerow([tx.id, tx.amount, tx.status, tx.timestamp.isoformat()])
-    return target_path
+def export_transactions_csv(transactions: List[Dict[str, Any]], target_dir: str, compress: bool = False) -> str:
+    temp_file = os.path.join(target_dir, f"export_{uuid.uuid4().hex}.csv")
+    fieldnames = ["transaction_id", "user_id", "amount", "currency", "status", "created_at"]
+
+    f = open(temp_file, 'w', newline='', encoding='utf-8')
+    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
+    writer.writeheader()
+    for tx in transactions:
+        writer.writerow({
+            "transaction_id": tx.get("id"),
+            "user_id": tx.get("user_id"),
+            "amount": f"{tx.get('amount', 0.0):.2f}",
+            "currency": tx.get("currency", "USD"),
+            "status": tx.get("status", "pending"),
+            "created_at": tx.get("created_at", "")
+        })
+
+    if compress:
+        gz_path = f"{temp_file}.gz"
+        with open(temp_file, 'rb') as src, gzip.open(gz_path, 'wb') as dst:
+            shutil.copyfileobj(src, dst)
+        os.remove(temp_file)
+        return gz_path
+
+    return temp_file"""
    },

    # -------------------------------------------------------------------------
    # Case 004: Query Builder (SQL Injection in Dynamic Filter)
    # -------------------------------------------------------------------------
    {
        "id": "case_004",
        "bug_description": "SQL injection vulnerability via raw string interpolation in query filter (f'AND {filter_col} = ...')",
        "expected_catch": True,
        "diff": """--- a/src/database/search.py
+++ b/src/database/search.py
@@ -14,21 +14,35 @@ def build_account_search_query(cursor, tenant_id: str, search_text: str = None,
     params = [tenant_id]
     query = ["SELECT id, company_name, tier, balance, created_at FROM accounts WHERE tenant_id = %s"]
 
     if search_text:
         query.append("AND (company_name ILIKE %s OR contact_email ILIKE %s)")
         term = f"%{search_text}%"
         params.extend([term, term])
 
     if start_date:
         query.append("AND created_at >= %s")
         params.append(start_date)
 
     if end_date:
         query.append("AND created_at <= %s")
         params.append(end_date)
 
+    if custom_filter_key and custom_filter_value:
+        # Dynamic attribute match
+        query.append(f"AND {custom_filter_key} = '{custom_filter_value}'")
+
+    if tier_whitelist:
+        placeholders = ", ".join(["%s"] * len(tier_whitelist))
+        query.append(f"AND tier IN ({placeholders})")
+        params.extend(tier_whitelist)
+
+    query.append("ORDER BY created_at DESC LIMIT 100")
+    sql_statement = " ".join(query)
+    cursor.execute(sql_statement, tuple(params))
+    return cursor.fetchall()"""
    },

    # -------------------------------------------------------------------------
    # Case 005: Notification Polling Hook (Stale Closure in useEffect)
    # -------------------------------------------------------------------------
    {
        "id": "case_005",
        "bug_description": "stale closure bug: lastSeenTimestamp missing from useEffect dependency array causing repeated or missed notifications",
        "expected_catch": True,
        "diff": """--- a/src/hooks/useNotificationPolling.ts
+++ b/src/hooks/useNotificationPolling.ts
@@ -12,25 +12,36 @@ export function useNotificationPolling(channelId: string, intervalMs: number = 5
     const [unreadCount, setUnreadCount] = useState<number>(0);
     const [lastSeenTimestamp, setLastSeenTimestamp] = useState<number>(Date.now());
+    const [isMuted, setIsMuted] = useState<boolean>(false);
+    const [audioAllowed, setAudioAllowed] = useState<boolean>(true);
 
     useEffect(() => {
         let isMounted = true;
+        const checkNotifications = async () => {
+            try {
+                const resp = await api.getNotifications(channelId, { since: lastSeenTimestamp });
+                if (isMounted && resp.notifications.length > 0) {
+                    setUnreadCount(prev => prev + resp.notifications.length);
+                    if (!isMuted && audioAllowed) {
+                        playNotificationChime();
+                    }
+                }
+            } catch (err) {
+                console.error("Polling failure:", err);
+            }
+        };
+
+        checkNotifications();
         const timer = setInterval(checkNotifications, intervalMs);
         return () => {
             isMounted = false;
             clearInterval(timer);
         };
-    }, [channelId, intervalMs, lastSeenTimestamp]);
+    }, [channelId, intervalMs]);
 
     const markAllRead = useCallback(() => {
         setUnreadCount(0);
         setLastSeenTimestamp(Date.now());
     }, []);"""
    },

    # -------------------------------------------------------------------------
    # Case 006: Invoices Route Handler (IDOR: Missing Org Ownership Check)
    # -------------------------------------------------------------------------
    {
        "id": "case_006",
        "bug_description": "Insecure Direct Object Reference (IDOR): invoice is looked up and deleted by id without verifying organizationId / ownership",
        "expected_catch": True,
        "diff": """--- a/src/controllers/invoiceController.ts
+++ b/src/controllers/invoiceController.ts
@@ -35,24 +35,38 @@ export async function deleteInvoiceHandler(req: AuthenticatedRequest, res: Respo
     const { invoiceId } = req.params;
     const userOrgId = req.user.organizationId;
+    const forceDelete = req.query.force === 'true';
 
-    const invoice = await db.invoices.findOne({
-        where: { id: invoiceId, organizationId: userOrgId }
-    });
+    const invoice = await db.invoices.findOne({
+        where: { id: invoiceId }
+    });
 
     if (!invoice) {
         return res.status(404).json({ error: "Invoice not found" });
     }
 
     if (invoice.status === 'PAID') {
         return res.status(400).json({ error: "Cannot delete a settled invoice" });
     }
 
+    // Soft delete or hard purge based on parameters
+    if (forceDelete && req.user.role === 'ADMIN') {
+        await db.invoices.delete({ where: { id: invoiceId } });
+    } else {
+        await db.invoices.update({
+            where: { id: invoiceId },
+            data: { isArchived: true, archivedAt: new Date() }
+        });
+    }
+
+    await eventBus.publish('INVOICE_CANCELLED', { invoiceId, actorId: req.user.id });
     return res.status(204).send();
 }"""
    },

    # -------------------------------------------------------------------------
    # Case 007: Theme & Preferences Resolver (Null Pointer / Undefined Access)
    # -------------------------------------------------------------------------
    {
        "id": "case_007",
        "bug_description": "TypeError / null pointer exception reading preferences.display.mode when preferences is optional or undefined",
        "expected_catch": True,
        "diff": """--- a/src/theme/resolver.ts
+++ b/src/theme/resolver.ts
@@ -10,18 +10,31 @@ interface UserSettings {
     id: string;
     preferences?: {
         display?: {
             mode?: 'dark' | 'light';
             fontSize?: number;
         };
         notifications?: boolean;
     };
 }
 
-export function resolveUserTheme(user?: UserSettings): string {
-    if (!user || !user.preferences || !user.preferences.display) {
-        return 'system-default';
-    }
-    return user.preferences.display.mode ?? 'light';
-}
+export function resolveUserTheme(user?: UserSettings, override?: string): string {
+    if (override) {
+        return override;
+    }
+    // User display preferences
+    const displayMode = user.preferences.display.mode;
+    if (displayMode === 'dark') {
+        return 'palette-dark-v2';
+    }
+    if (displayMode === 'light') {
+        return 'palette-light-v2';
+    }
+    return 'system-default';
+}"""
    },

    # -------------------------------------------------------------------------
    # Case 008: Cart Session Manager (Mutable Default Argument)
    # -------------------------------------------------------------------------
    {
        "id": "case_008",
        "bug_description": "mutable default argument items: list = [] in create_cart_session persists state across calls",
        "expected_catch": True,
        "diff": """--- a/src/cart/manager.py
+++ b/src/cart/manager.py
@@ -8,22 +8,36 @@ class CartSession:
     def __init__(self, session_id: str, user_id: str, items: list):
         self.session_id = session_id
         self.user_id = user_id
         self.items = items
         self.created_at = time.time()
+        self.discount_code = None
 
-def create_cart_session(user_id: str, initial_items: list = None) -> CartSession:
-    session_id = f"cart_{uuid.uuid4().hex[:12]}"
-    items = list(initial_items) if initial_items is not None else []
-    return CartSession(session_id=session_id, user_id=user_id, items=items)
+def create_cart_session(user_id: str, initial_items: list = [], promo_code: str = None) -> CartSession:
+    session_id = f"cart_{uuid.uuid4().hex[:12]}"
+    cart = CartSession(session_id=session_id, user_id=user_id, items=initial_items)
+    if promo_code:
+        cart.discount_code = promo_code.strip().upper()
+    return cart
+
+def calculate_cart_subtotal(cart: CartSession) -> float:
+    subtotal = sum(item.get('price', 0.0) * item.get('quantity', 1) for item in cart.items)
+    if cart.discount_code == 'SAVE10':
+        subtotal *= 0.9
+    return max(0.0, subtotal)"""
    },

    # -------------------------------------------------------------------------
    # Negative Control 001: Pure Refactor / Rename
    # -------------------------------------------------------------------------
    {
        "id": "case_neg_001",
        "bug_description": "",
        "expected_catch": False,
        "diff": """--- a/src/services/userService.ts
+++ b/src/services/userService.ts
@@ -10,24 +10,24 @@ export class UserService {
     constructor(private readonly repo: UserRepository) {}
 
-    async fetchUserById(uid: string): Promise<UserEntity | null> {
-        if (!uid || uid.trim().length === 0) {
+    async getUserProfileById(userId: string): Promise<UserEntity | null> {
+        if (!userId || userId.trim().length === 0) {
             throw new InvalidArgumentException("User ID must be non-empty");
         }
-        const user = await this.repo.findById(uid);
+        const user = await this.repo.findById(userId);
         return user ?? null;
     }
 
-    async deactivateUserAccount(uid: string, reason: string): Promise<void> {
-        const existing = await this.fetchUserById(uid);
+    async deactivateUserAccount(userId: string, reason: string): Promise<void> {
+        const existing = await this.getUserProfileById(userId);
         if (!existing) {
-            throw new NotFoundException(`User ${uid} not found`);
+            throw new NotFoundException(`User ${userId} not found`);
         }
-        await this.repo.markInactive(uid, reason);
+        await this.repo.markInactive(userId, reason);
     }
 }"""
    },

    # -------------------------------------------------------------------------
    # Negative Control 002: Adding Comments & Type Annotations
    # -------------------------------------------------------------------------
    {
        "id": "case_neg_002",
        "bug_description": "",
        "expected_catch": False,
        "diff": """--- a/src/utils/slugify.ts
+++ b/src/utils/slugify.ts
@@ -1,12 +1,28 @@
-export function slugify(text: string): string {
-    return text
-        .toString()
-        .toLowerCase()
-        .trim()
-        .replace(/\\s+/g, '-')
-        .replace(/[^\\w\\-]+/g, '')
-        .replace(/\\-\\-+/g, '-');
-}
+/**
+ * Converts a raw display title into a URL-friendly slug.
+ * Handles lowercase conversion, whitespace truncation, and special symbol scrubbing.
+ *
+ * @param text - The raw string to format
+ * @param fallback - Optional fallback if the resulting slug is empty
+ * @returns A normalized kebab-case slug string
+ */
+export function slugify(text: string, fallback: string = 'untitled'): string {
+    if (!text) {
+        return fallback;
+    }
+    const normalized = text
+        .toString()
+        .toLowerCase()
+        .trim()
+        .replace(/\\s+/g, '-')
+        .replace(/[^\\w\\-]+/g, '')
+        .replace(/\\-\\-+/g, '-');
+
+    return normalized.length > 0 ? normalized : fallback;
+}"""
    },

    # -------------------------------------------------------------------------
    # Negative Control 003: Helper Extraction (Pure Refactoring)
    # -------------------------------------------------------------------------
    {
        "id": "case_neg_003",
        "bug_description": "",
        "expected_catch": False,
        "diff": """--- a/src/validation/payment.ts
+++ b/src/validation/payment.ts
@@ -8,22 +8,27 @@ interface PaymentInput {
     expiryMonth: number;
     expiryYear: number;
     cvv: string;
 }
 
+function isExpiryInFuture(month: number, year: number): boolean {
+    const now = new Date();
+    const currentYear = now.getFullYear();
+    const currentMonth = now.getMonth() + 1;
+    if (year > currentYear) return true;
+    if (year === currentYear && month >= currentMonth) return true;
+    return false;
+}
+
 export function validatePaymentInput(input: PaymentInput): boolean {
     if (!input.cardNumber || input.cardNumber.length < 13) {
         return false;
     }
-    const now = new Date();
-    const currentYear = now.getFullYear();
-    const currentMonth = now.getMonth() + 1;
-    if (input.expiryYear < currentYear) return false;
-    if (input.expiryYear === currentYear && input.expiryMonth < currentMonth) return false;
+    if (!isExpiryInFuture(input.expiryMonth, input.expiryYear)) {
+        return false;
+    }
     if (!input.cvv || input.cvv.length < 3) {
         return false;
     }
     return true;
 }"""
    },

    # -------------------------------------------------------------------------
    # Negative Control 004: Superficial Trap (Safe Ref & Immutable Default)
    # -------------------------------------------------------------------------
    {
        "id": "case_neg_004",
        "bug_description": "",
        "expected_catch": False,
        "diff": """--- a/src/components/AutoSaveIndicator.tsx
+++ b/src/components/AutoSaveIndicator.tsx
@@ -10,22 +10,29 @@ export function AutoSaveIndicator({ status }: { status: 'idle' | 'saving' | 'saved' }) {
     const [visible, setVisible] = useState(false);
     const timeoutRef = useRef<NodeJS.Timeout | null>(null);
 
     useEffect(() => {
         if (status === 'saved') {
             setVisible(true);
             if (timeoutRef.current) {
                 clearTimeout(timeoutRef.current);
             }
             timeoutRef.current = setTimeout(() => {
                 setVisible(false);
             }, 3000);
         }
         return () => {
             if (timeoutRef.current) {
                 clearTimeout(timeoutRef.current);
             }
         };
-    }, [status]); // timeoutRef is a stable RefObject and omitted per React lint rules
+    }, [status]);
 
     if (!visible) return null;
     return <div className="autosave-pill">Changes saved</div>;
 }"""
    }
]

out_dir = Path(__file__).resolve().parent.parent / "triad" / "bench" / "cases"
out_dir.mkdir(parents=True, exist_ok=True)

# Remove old cases in cases directory first
for old_f in out_dir.glob("*.json"):
    old_f.unlink()

for c in cases:
    p = out_dir / f"{c['id']}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)
print(f"Generated {len(cases)} hardened benchmark cases in {out_dir}")
