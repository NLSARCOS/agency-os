   -- Idempotent backfill
   INSERT INTO user_tenants (user_id, tenant_id, role)
   SELECT id, 'legacy-tenant', 'admin' FROM users
   ON CONFLICT DO NOTHING;
   ```

2. **Traffic Splitting**
   - 5% of users → V2 auth (monitor error rates)
   - Validate JWT tokens work with existing API
   - Rollback criterion: >0.1% auth failure rate

### Phase 3: Cutover (Week 4)
**Goal:** Switch primary auth to V2

1. **Critical Path**
   - Set `USE_V2_AUTH` default true
   - Maintain legacy session validation for 48h (grace period)
   - Monitor: Auth latency p99 <200ms

2. **Cleanup**
   - Remove legacy auth tables (30 days later)
   - Archive old session data

---

## 4. Security Implementation

### 4.1 Authentication Hardening
- **Passwords:** Argon2id (memory-hard, resistant to GPU cracking)
- **JWT:** RS256 (asymmetric), 15min access / 7d refresh rotation
- **Headers:** Strict-Transport-Security, CSP, X-Frame-Options
- **Rate Limiting:** 5 attempts/IP/minute (Redis-backed)

### 4.2 RBAC Enforcement Points