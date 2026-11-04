import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { Button, ErrorText, Modal, inputClass } from "../../components/ui";

export function RequestAccessDialog({
  datasetCode,
  datasetName,
  open,
  onClose,
}: {
  datasetCode: string;
  datasetName: string;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: () => api.requestAccess(datasetCode, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-requests"] });
      queryClient.invalidateQueries({ queryKey: ["datasets"] });
    },
  });

  return (
    <Modal open={open} title={`Yêu cầu truy cập: ${datasetName}`} onClose={onClose}>
      {mutation.isSuccess ? (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            Đã gửi yêu cầu. Quản trị viên sẽ xét duyệt; sau khi được cấp quyền, bạn hãy đặt lại câu hỏi.
          </p>
          <Button onClick={onClose}>Đóng</Button>
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
        >
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Lý do cần truy cập</span>
            <textarea
              className={inputClass}
              rows={4}
              minLength={10}
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Ví dụ: Cần đánh giá KPI đội kinh doanh khu vực miền Nam quý 4"
            />
          </label>
          <ErrorText error={mutation.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              Hủy
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              Gửi yêu cầu
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
