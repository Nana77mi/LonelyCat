export type OneBotEvent = {
  type: string;
  payload: Record<string, unknown>;
};

export const parseEvent = (body: unknown): OneBotEvent => {
  // TODO: validate OneBot v11 payloads
  return {
    type: "unknown",
    payload: (body ?? {}) as Record<string, unknown>,
  };
};
