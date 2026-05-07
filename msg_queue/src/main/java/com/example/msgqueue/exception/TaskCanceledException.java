package com.example.msgqueue.exception;

public class TaskCanceledException extends RuntimeException {

    public TaskCanceledException(String message) {
        super(message);
    }
}
