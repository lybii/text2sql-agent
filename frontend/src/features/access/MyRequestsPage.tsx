import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";

import { api } from "../../api/client";
import type { AccessRequest } from "../../api/types";
import { Badge, Button, Card, EmptyState, ErrorText, Spinner, type Tone } from "../../components/ui";
import { formatDateTime } from "../../lib/format";

export const REQUEST_STATUS: Record<AccessRequest["status"], { label: string; tone: Tone }> = {
  pending: { label: "Chờ duyệt", tone: "amber" },
  approved: { label: "Đã duyệt", tone: "green" },
  rejected: { label: "Bị từ chối", tone: "red" },
  cancelled: { label: "Đã hủy", tone: "slate" },
};

export function MyRequestsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["my-requests"], queryFn: api.myRequests });
  const cancel = useMutation({
    mutationFn: api.cancelRequest,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["my-requests"] }),
  });

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <h1 className="text-xl font-semibold">Yêu cầu truy cập của tôi</h1>
        <p className="mt-1 text-sm text-slate-500">Gửi yêu cầu từ trang Danh mục dữ liệu hoặc ngay trong cuộc trò chuyện.</p>
        <div className="mt-6 space-y-3">
          {isLoading && <Spinner label="Đang tải…" />}
          <ErrorText error={error ?? cancel.error} />
          {data?.length === 0 && <EmptyState icon={<KeyRound className="size-10" />} title="Bạn chưa gửi yêu cầu nào" />}
          {data?.map((r) => (
            <Card key={r.id} className="p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="font-medium">{r.dataset_name}</p>
                  <p className="mt-1 text-sm text-slate-600">{r.reason}</p>
                  <p className="mt-2 text-xs text-slate-400">Gửi lúc {formatDateTime(r.created_at)}</p>
                  {r.reviewed_at && (
                    <p className="mt-1 text-xs text-slate-500">
                      {r.reviewer_name} · {formatDateTime(r.reviewed_at)}
                      {r.review_comment && <> — “{r.review_comment}”</>}
                      {r.expires_at && <> · hết hạn {formatDateTime(r.expires_at)}</>}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <Badge tone={REQUEST_STATUS[r.status].tone}>{REQUEST_STATUS[r.status].label}</Badge>
                  {r.status === "pending" && (
                    <Button size="sm" variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate(r.id)}>
                      Hủy yêu cầu
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
