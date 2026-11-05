import { useCallback, useRef, useState } from 'react';
import { CircleAlert } from 'lucide-react';
import { Modal } from '../components/Dialogs';

type Question = { title: string; message: string; action: string; danger?: boolean };

export function useConfirmation() {
  const [question, setQuestion] = useState<Question | null>(null);
  const answer = useRef<((value: boolean) => void) | null>(null);
  const confirm = useCallback(
    (next: Question) =>
      new Promise<boolean>((resolve) => {
        answer.current?.(false);
        answer.current = resolve;
        setQuestion(next);
      }),
    [],
  );
  const finish = useCallback((value: boolean) => {
    answer.current?.(value);
    answer.current = null;
    setQuestion(null);
  }, []);
  const confirmation = question && (
    <Modal title={question.title} onClose={() => finish(false)}>
      <div className={`confirmation-body ${question.danger ? 'danger' : ''}`}>
        <CircleAlert size={26} />
        <p>{question.message}</p>
      </div>
      <div className="modal-footer">
        <button className="button secondary" data-autofocus onClick={() => finish(false)}>
          取消
        </button>
        <button
          className={`button ${question.danger ? 'danger' : 'primary'}`}
          onClick={() => finish(true)}
        >
          {question.action}
        </button>
      </div>
    </Modal>
  );
  return { confirm, confirmation };
}
