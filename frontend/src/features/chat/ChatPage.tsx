import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bot, MessageSquarePlus, SendHorizontal, Sparkles, Trash2, User as UserIcon } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "../../api/client";
import type { ConversationDetail, Message, QueryRun } from "../../api/types";
import { EmptyState, ErrorText, Spinner } from "../../components/ui";
import { QueryCard, type QueryActions } from "./QueryCard";

const SUGGESTIONS = [
  "Doanh thu theo thành phố năm 2025",
  "Top 5 dự án có doanh thu cao nhất quý 2/2025",
  "Doanh thu căn hộ tại Hà Nội theo tháng năm 2025",
  "Tồn kho theo dự án",
  "Số khách hàng mới theo nguồn khách năm 2025",
  "Doanh thu là bao nhiêu?",
];

function ConversationList({ activeId }: { activeId: number | null }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });
  const remove = useMutation({
    mutationFn: api.deleteConversation,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (id === activeId) navigate("/chat");
    },
  });

  return (
    <div className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="p-3">
        <button
          onClick={() => navigate("/chat")}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50"
        >
          <MessageSquarePlus className="size-4" /> Cuộc trò chuyện mới
        </button>
      </div>
      <div className="scroll-thin flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {isLoading && <div className="p-3"><Spinner /></div>}
        {data?.map((c) => (
          <div
            key={c.id}
            className={clsx(
              "group flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm",
              c.id === activeId ? "bg-brand-50 text-brand-700" : "text-slate-700 hover:bg-slate-100",
            )}
            onClick={() => navigate(`/chat/${c.id}`)}
          >
            <span className="flex-1 truncate">{c.title}</span>
            <button
              aria-label="Xóa cuộc trò chuyện"
              className="hidden text-slate-400 hover:text-rose-600 group-hover:block"
              onClick={(e) => {
                e.stopPropagation();
                remove.mutate(c.id);
              }}
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        ))}
        {data?.length === 0 && <p className="px-3 py-2 text-xs text-slate-400">Chưa có cuộc trò chuyện nào.</p>}
      </div>
    </div>
  );
}

function MessageBubble({ message, actions }: { message: Message; actions: QueryActions }) {
  const isUser = message.role === "user";
  return (
    <div className={clsx("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={clsx(
          "flex size-8 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-slate-200 text-slate-600" : "bg-brand-600 text-white",
        )}
      >
        {isUser ? <UserIcon className="size-4" /> : <Bot className="size-4" />}
      </div>
      <div
        className={clsx(
          "min-w-0 rounded-2xl px-4 py-3",
          isUser ? "max-w-[75%] bg-brand-600 text-white" : "w-full max-w-3xl border border-slate-200 bg-white shadow-sm",
        )}
      >
        {isUser || !message.query ? (
          <p className="whitespace-pre-wrap text-sm">{message.content}</p>
        ) : (
          <QueryCard run={message.query} reply={message.content} actions={actions} />
        )}
      </div>
    </div>
  );
}

export function ChatPage() {
  const params = useParams();
  const conversationId = params.conversationId ? Number(params.conversationId) : null;
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = searchParams.get("q");
    if (q) {
      setDraft(q);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const detailKey = ["conversation", conversationId];
  const { data: detail, isLoading } = useQuery({
    queryKey: detailKey,
    queryFn: () => api.conversation(conversationId!),
    enabled: conversationId !== null,
  });

  const send = useMutation({
    mutationFn: async (content: string) => {
      let id = conversationId;
      if (id === null) id = (await api.createConversation()).id;
      const turn = await api.sendMessage(id, content);
      return { id, turn };
    },
    onMutate: (content) => setPending(content),
    onSettled: () => setPending(null),
    onSuccess: ({ id }) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["conversation", id] });
      if (id !== conversationId) navigate(`/chat/${id}`);
    },
  });

  const replaceRun = (run: QueryRun): void => {
    queryClient.setQueryData<ConversationDetail>(detailKey, (old) =>
      old && { ...old, messages: old.messages.map((m) => (m.query?.id === run.id ? { ...m, query: run } : m)) },
    );
  };

  const actions: QueryActions = {
    approve: async (run) => {
      replaceRun({ ...run, status: "running" });
      try {
        replaceRun(await api.approve(run.id, run.sql_hash!));
      } catch (e) {
        replaceRun(run);
        throw e;
      }
    },
    edit: async (run, sql) => replaceRun(await api.edit(run.id, sql)),
    cancel: async (run) => replaceRun(await api.cancel(run.id)),
    feedback: (run, rating) => api.feedback(run.id, rating),
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail?.messages.length, pending]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const content = draft.trim();
    if (!content || send.isPending) return;
    setDraft("");
    send.mutate(content);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) submit();
  };

  const messages = conversationId ? (detail?.messages ?? []) : [];

  return (
    <div className="flex h-full">
      <ConversationList activeId={conversationId} />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="scroll-thin flex-1 overflow-y-auto">
          <div className="mx-auto max-w-4xl space-y-6 px-6 py-6">
            {isLoading && conversationId && <Spinner label="Đang tải…" />}
            {messages.length === 0 && !pending && !isLoading && (
              <EmptyState icon={<Sparkles className="size-10" />} title="Hỏi dữ liệu bán hàng bằng tiếng Việt">
                <p className="max-w-md text-sm">
                  Trợ lý sẽ lập truy vấn, giải thích cách hiểu và chờ bạn <b>duyệt SQL</b> trước khi chạy trên dữ liệu.
                </p>
                <div className="mt-4 flex max-w-2xl flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => setDraft(s)}
                      className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:border-brand-500 hover:text-brand-700"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </EmptyState>
            )}
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} actions={actions} />
            ))}
            {pending && (
              <>
                <MessageBubble
                  message={{ id: -1, role: "user", content: pending, created_at: "", query: null }}
                  actions={actions}
                />
                <div className="pl-11">
                  <Spinner label="Đang phân tích câu hỏi và lập truy vấn…" />
                </div>
              </>
            )}
            <ErrorText error={send.error} />
            <div ref={bottomRef} />
          </div>
        </div>
        <form onSubmit={submit} className="border-t border-slate-200 bg-white px-6 py-4">
          <div className="mx-auto flex max-w-4xl items-end gap-2 rounded-xl border border-slate-300 bg-white p-2 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              rows={1}
              maxLength={500}
              placeholder="Ví dụ: Doanh thu căn hộ tại Hà Nội theo tháng năm 2025"
              className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none"
            />
            <button
              type="submit"
              disabled={!draft.trim() || send.isPending}
              aria-label="Gửi"
              className="rounded-lg bg-brand-600 p-2 text-white hover:bg-brand-700 disabled:opacity-40"
            >
              <SendHorizontal className="size-4" />
            </button>
          </div>
          <p className="mx-auto mt-1.5 max-w-4xl text-[11px] text-slate-400">
            SQL chỉ chạy sau khi bạn duyệt · truy vấn chỉ đọc trên vùng dữ liệu an toàn · tối đa 500 dòng
          </p>
        </form>
      </div>
    </div>
  );
}
