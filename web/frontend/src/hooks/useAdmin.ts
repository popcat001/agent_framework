import { useEffect, useState } from "react";
import { api, type AdminMe } from "../services/api";

/**
 * Fetches `/api/admin/me` once on mount. Used to gate the "Manage access"
 * sidebar entry and to scope the AdminAccessPage. Returns null while the
 * request is in flight, then either an `AdminMe` payload or a non-admin
 * payload (`is_admin: false`).
 */
export function useAdmin(): { me: AdminMe | null; loading: boolean } {
  const [me, setMe] = useState<AdminMe | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .adminMe()
      .then((data) => {
        if (!cancelled) setMe(data);
      })
      .catch(() => {
        if (!cancelled)
          setMe({
            is_admin: false,
            is_super_admin: false,
            managed_agents: [],
            super_admins: [],
          });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { me, loading };
}
