package com.example.msgqueue.controller;

import com.example.msgqueue.exception.QueueBusyException;
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
}

