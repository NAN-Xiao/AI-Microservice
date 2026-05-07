package com.example.msgqueue.service;

import com.example.msgqueue.config.SeeThroughProperties;
import com.example.msgqueue.exception.TaskCanceledException;
import com.example.msgqueue.model.SeeThroughResult;
import com.example.msgqueue.model.SeeThroughTask;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.client.RestTemplateBuilder;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SeeThroughTaskQueueServiceTest {

    @Test
    void shouldApplyCancelThatArrivesBeforeTaskRegistration() throws Exception {
        SeeThroughProperties properties = new SeeThroughProperties();
        properties.setMaxSize(10);
        properties.setRequestTimeoutSeconds(5);

        BlockingSeeThroughClient client = new BlockingSeeThroughClient(properties);
        SeeThroughTaskQueueService service = new SeeThroughTaskQueueService(properties, client);
        service.start();

        try {
            assertTrue(service.cancel("early-cancel", "page closed before upload completed"));

            SeeThroughTask task = SeeThroughTask.of("early-cancel", "early.png", "image/png", new byte[]{1}, null);
            service.submit(task);

            Throwable cancelError = CompletableFuture
                    .supplyAsync(() -> waitForResult(service, task))
                    .handle((result, error) -> error)
                    .get(2, TimeUnit.SECONDS);

            assertInstanceOf(TaskCanceledException.class, cancelError.getCause());
            assertEquals(0, service.stats().queueSize());
            assertEquals(1, service.stats().canceledCount());
        } finally {
            service.shutdown();
        }
    }

    @Test
    void shouldCancelQueuedTaskBeforeItStarts() throws Exception {
        SeeThroughProperties properties = new SeeThroughProperties();
        properties.setMaxSize(10);
        properties.setRequestTimeoutSeconds(5);

        BlockingSeeThroughClient client = new BlockingSeeThroughClient(properties);
        SeeThroughTaskQueueService service = new SeeThroughTaskQueueService(properties, client);
        service.start();

        try {
            SeeThroughTask runningTask = SeeThroughTask.of("running", "running.png", "image/png", new byte[]{1}, null);
            service.submit(runningTask);
            CompletableFuture<SeeThroughResult> runningFuture = CompletableFuture.supplyAsync(() -> waitForResult(service, runningTask));
            assertTrue(client.runningStarted.await(2, TimeUnit.SECONDS));

            SeeThroughTask queuedTask = SeeThroughTask.of("queued", "queued.png", "image/png", new byte[]{2}, null);
            service.submit(queuedTask);
            CompletableFuture<SeeThroughResult> queuedFuture = CompletableFuture.supplyAsync(() -> waitForResult(service, queuedTask));
            awaitQueueSize(service, 1);

            assertTrue(service.cancel("queued", "client closed page"));
            assertEquals(0, service.stats().queueSize());
            assertEquals(1, service.stats().canceledCount());

            Throwable cancelError = queuedFuture.handle((result, error) -> error).get(2, TimeUnit.SECONDS);
            assertInstanceOf(TaskCanceledException.class, cancelError.getCause());

            client.releaseRunning.countDown();
            runningFuture.get(2, TimeUnit.SECONDS);
        } finally {
            client.releaseRunning.countDown();
            service.shutdown();
        }
    }

    private SeeThroughResult waitForResult(SeeThroughTaskQueueService service, SeeThroughTask task) {
        try {
            return service.waitForResult(task);
        } catch (RuntimeException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new RuntimeException(ex);
        }
    }

    private void awaitQueueSize(SeeThroughTaskQueueService service, int expectedSize) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
        while (System.nanoTime() < deadline) {
            if (service.stats().queueSize() == expectedSize) {
                return;
            }
            Thread.sleep(10);
        }
        assertEquals(expectedSize, service.stats().queueSize());
    }

    private static class BlockingSeeThroughClient extends SeeThroughClient {

        private final CountDownLatch runningStarted = new CountDownLatch(1);
        private final CountDownLatch releaseRunning = new CountDownLatch(1);

        BlockingSeeThroughClient(SeeThroughProperties properties) {
            super(properties, new RestTemplateBuilder());
        }

        @Override
        public SeeThroughResult convert(SeeThroughTask task) {
            if ("running".equals(task.taskId())) {
                runningStarted.countDown();
                try {
                    releaseRunning.await(2, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            return new SeeThroughResult(
                    task.filename().replace(".png", ".psd"),
                    "application/octet-stream",
                    "",
                    new byte[]{1, 2, 3},
                    List.of()
            );
        }
    }
}
