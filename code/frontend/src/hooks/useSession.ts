import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { ChatTurn, Schema, Session } from "../types";

interface SessionState {
  session: Session | null;
  schema: Schema | null;
  turns: ChatTurn[];
  deltaHistory: number[];
  loading: boolean;
  error: string | null;
}

export function useSession() {
  const [state, setState] = useState<SessionState>({
    session: null,
    schema: null,
    turns: [],
    deltaHistory: [],
    loading: false,
    error: null,
  });

  const setLoading = (loading: boolean) =>
    setState((s) => ({ ...s, loading, error: null }));

  const setError = (error: string) =>
    setState((s) => ({ ...s, loading: false, error }));

  // ── Create ──────────────────────────────────────────────────────────────────

  const createSession = useCallback(async (domain: string) => {
    setLoading(true);
    try {
      const res = await api.createSession(domain);
      setState((s) => ({
        ...s,
        loading: false,
        schema: res.schema,
        turns: [
          {
            role: "assistant",
            message:
              `Discovered an initial schema with **${res.schema.entity_classes.length} classes** ` +
              `and **${res.schema.relation_types.length} relation types** from ` +
              `${res.n_discovery_docs} sample documents.\n\n${res.message}`,
          },
        ],
      }));
      return res.session_id;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, []);

  // ── Load ────────────────────────────────────────────────────────────────────

  const loadSession = useCallback(async (sessionId: string) => {
    setLoading(true);
    try {
      const session = await api.getSession(sessionId);
      const history = await api.getHistory(sessionId);
      setState((s) => ({
        ...s,
        loading: false,
        session,
        schema: session.schema,
        deltaHistory: history.delta_history,
      }));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  // ── Chat ────────────────────────────────────────────────────────────────────

  const sendMessage = useCallback(
    async (sessionId: string, message: string) => {
      setState((s) => ({
        ...s,
        loading: true,
        turns: [...s.turns, { role: "user", message }],
      }));
      try {
        const res = await api.chat(sessionId, message);
        setState((s) => ({
          ...s,
          loading: false,
          schema: res.schema,
          deltaHistory: [...s.deltaHistory, res.delta_s],
          turns: [
            ...s.turns,
            {
              role: "assistant",
              message:
                res.explanation +
                (res.questions.length > 0 ? `\n\n> ${res.questions[0]}` : "") +
                (res.converged ? "\n\n✓ Schema has converged." : ""),
            },
          ],
        }));
        return res;
      } catch (e) {
        setError((e as Error).message);
        return null;
      }
    },
    []
  );

  // ── Freeze ──────────────────────────────────────────────────────────────────

  const freezeSchema = useCallback(async (sessionId: string) => {
    setLoading(true);
    try {
      const res = await api.freeze(sessionId);
      setState((s) => ({
        ...s,
        loading: false,
        schema: res.schema,
        turns: [
          ...s.turns,
          {
            role: "assistant",
            message: `Schema frozen at version ${res.schema.version}. You can now start batch extraction.`,
          },
        ],
      }));
      return res.schema;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, []);

  return {
    ...state,
    createSession,
    loadSession,
    sendMessage,
    freezeSchema,
  };
}