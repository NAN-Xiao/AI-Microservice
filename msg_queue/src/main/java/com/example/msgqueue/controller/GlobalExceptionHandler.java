package com.example.msgqueue.controller;

import com.example.msgqueue.exception.QueueBusyException;
import com.example.msgqueue.exception.SeeThroughTaskException;
import com.example.msgqueue.exception.TaskCanceledException;
import com.example.msgqueue.model.ErrorResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(QueueBusyException.class)
    public ResponseEntity<ErrorResponse> handleQueueBusy(QueueBusyException ex) {
        ErrorResponse body = new ErrorResponse(ex.getCode(), ex.getMessage());
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(body);
    }

    @ExceptionHandler(SeeThroughTaskException.class)
    public ResponseEntity<ErrorResponse> handleSeeThroughTask(SeeThroughTaskException ex) {
        ErrorResponse body = new ErrorResponse("SEE_THROUGH_FAILED", ex.getMessage());
        HttpStatus status = HttpStatus.resolve(ex.getStatusCode());
        return ResponseEntity.status(status == null ? HttpStatus.BAD_GATEWAY : status).body(body);
    }

    @ExceptionHandler(java.util.concurrent.TimeoutException.class)
    public ResponseEntity<ErrorResponse> handleTimeout(java.util.concurrent.TimeoutException ex) {
        ErrorResponse body = new ErrorResponse("TASK_TIMEOUT", "任务等待超时，请稍后重试");
        return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT).body(body);
    }

    @ExceptionHandler(TaskCanceledException.class)
    public ResponseEntity<ErrorResponse> handleTaskCanceled(TaskCanceledException ex) {
        ErrorResponse body = new ErrorResponse("TASK_CANCELED", ex.getMessage());
        return ResponseEntity.status(HttpStatus.REQUEST_TIMEOUT).body(body);
    }
}

