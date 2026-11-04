import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { api } from "../../api/client";
import type { AccessRequest } from "../../api/types";
import { Badge, Button, Card, EmptyState, ErrorText, Spinner, inputClass } from "../../components/ui";
import { formatDateTime } from "../../lib/format";
import { REQUEST_STATUS } from "../access/MyRequestsPage";

function RequestRow({ request }: { request: AccessRequest }) {
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [expires, setExpires] = useState("");
  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      api.decide(request.id, decision, comment, expires ? new Date(expires + "T23:59:59").toISOString() : undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-requests"] });
      queryClient.invalidateQueries({ queryKey: ["entitlements"] });
    },
  });
  const status = REQUEST_STATUS[request.status];

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-medium">
            {request.requester_name} <span className="font-normal text-slate-400">({request.requester_email})</span>
          </p>
          <p className="text-sm text-slate-600">
            xin truy cập <b>{request.dataset_name}</b> · {formatDateTime(request.created_at)}
          </p>
          <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">“{request.reason}”</p>
          {request.reviewed_at && (
            <p className="mt-2 text-xs text-slate-500">
              {request.reviewer_name} · {formatDateTime(request.reviewed_at)}
              {request.review_comment && <> — “{request.review_comment}”</>}
            </p>
          )}
        </div>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>
      {request.status === "pending" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input className={clsx(inputClass, "max-w-xs")} placeholder="Ghi chú (bắt buộc khi từ chối)" value={comment} onChange={(e) => setComment(e.target.value)} />
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            Hết hạn
            <input className={clsx(inputClass, "w-40")} type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
          </label>
          <Button size="sm" loading={decide.isPending && decide.variables === "approve"} onClick={() => decide.mutate("approve")}>
            Phê duyệt
          </Button>
          <Button size="sm" variant="danger" loading={decide.isPending && decide.variables === "reject"} onClick={() => decide.mutate("reject")}>
            Từ chối
          </Button>
          <ErrorText error={decide.error} />
        </div>
      )}
    </Card>
  );
}

export function AdminAccessPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<"pending" | "all">("pending");
  const requests = useQuery({ queryKey: ["admin-requests", filter], queryFn: () => api.adminRequests(filter) });
  const entitlements = useQuery({ queryKey: ["entitlements"], queryFn: api.entitlements });
  const revoke = useMutation({
    mutationFn: api.revoke,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["entitlements"] }),
  });

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <h1 className="text-xl font-semibold">Duyệt quyền truy cập dữ liệu</h1>
        <p className="mt-1 text-sm text-slate-500">
          Quản trị viên duyệt quyền nhưng không mặc nhiên được đọc dữ liệu, và không thể tự duyệt yêu cầu của mình.
        </p>

        <div className="mt-6 flex gap-1 rounded-lg bg-slate-100 p-1 text-sm w-fit">
          {(["pending", "all"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={clsx("rounded-md px-3 py-1", filter === f ? "bg-white font-medium shadow-sm" : "text-slate-500")}
            >
              {f === "pending" ? "Chờ duyệt" : "Tất cả"}
            </button>
          ))}
        </div>
        <div className="mt-4 space-y-3">
          {requests.isLoading && <Spinner label="Đang tải…" />}
          <ErrorText error={requests.error} />
          {requests.data?.length === 0 && <EmptyState icon={<ShieldCheck className="size-10" />} title="Không có yêu cầu nào" />}
          {requests.data?.map((r) => (
            <RequestRow key={r.id} request={r} />
          ))}
        </div>

        <h2 className="mt-10 font-semibold">Quyền đang hiệu lực</h2>
        <Card className="mt-3 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Người dùng</th>
                <th className="px-4 py-2">Dataset</th>
                <th className="px-4 py-2">Cấp lúc</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {entitlements.data?.map((e) => (
                <tr key={e.id}>
                  <td className="px-4 py-2">
                    {e.user_name} <span className="text-slate-400">({e.user_email})</span>
                  </td>
                  <td className="px-4 py-2">{e.dataset_name}</td>
                  <td className="px-4 py-2 text-slate-500">{formatDateTime(e.granted_at)}</td>
                  <td className="px-4 py-2 text-right">
                    <Button size="sm" variant="ghost" onClick={() => revoke.mutate(e.id)} loading={revoke.isPending && revoke.variables === e.id}>
                      Thu hồi
                    </Button>
                  </td>
                </tr>
              ))}
              {entitlements.data?.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                    Chưa có quyền nào được cấp.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
