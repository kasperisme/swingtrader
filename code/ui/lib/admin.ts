const parseAdminUserIds = (raw: string | undefined): Set<string> => {
  if (!raw) return new Set();
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
};

let cached: Set<string> | null = null;

export function getAdminUserIds(): Set<string> {
  if (cached === null) {
    cached = parseAdminUserIds(process.env.ADMIN_USER_IDS);
  }
  return cached;
}

export function isAdmin(userId: string | null | undefined): boolean {
  if (!userId) return false;
  return getAdminUserIds().has(userId);
}

export function assertIsAdmin(userId: string | null | undefined): void {
  if (!isAdmin(userId)) {
    throw new Error("Admin access required");
  }
}
