import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthStore {
  userId: string | null;
  login: (id: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set) => ({
      userId: null,
      login: (id) => set({ userId: id }),
      logout: () => set({ userId: null }),
    }),
    { name: "dagent-auth", partialize: (s) => ({ userId: s.userId }) }
  )
);
