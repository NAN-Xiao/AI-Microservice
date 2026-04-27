package com.example.msgqueue.exception;

public class QueueBusyException extends RuntimeException {

    public static final String CODE = "TASK_BUSY";

    private final String code;

    public QueueBusyException() {
        super("任务繁忙，请稍后重试");
        this.code = CODE;
    }

    public String getCode() {
        return code;
    }
}

