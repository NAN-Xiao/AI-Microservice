package com.example.msgqueue.service;

import com.example.msgqueue.config.SeeThroughProperties;
import com.example.msgqueue.exception.SeeThroughTaskException;
import com.example.msgqueue.model.SeeThroughResult;
import com.example.msgqueue.model.SeeThroughTask;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.web.util.UriComponentsBuilder;

import java.time.Duration;
import java.util.List;
import java.net.URI;

@Service
public class SeeThroughClient {

    private final SeeThroughProperties properties;
    private final RestTemplate restTemplate;

    public SeeThroughClient(SeeThroughProperties properties, RestTemplateBuilder restTemplateBuilder) {
        this.properties = properties;
        this.restTemplate = restTemplateBuilder
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(properties.getRequestTimeoutSeconds()))
                .build();
    }

    public SeeThroughResult convert(SeeThroughTask task) {
        String url = buildUrl("/api/see-through/convert");

        HttpHeaders fileHeaders = new HttpHeaders();
        fileHeaders.setContentType(MediaType.parseMediaType(task.contentType()));
        fileHeaders.setContentDisposition(ContentDisposition.formData()
                .name("image")
                .filename(task.filename())
                .build());

        HttpEntity<ByteArrayMultipartFileResource> filePart = new HttpEntity<>(
                new ByteArrayMultipartFileResource(task.imageBytes(), task.filename()),
                fileHeaders
        );

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("image", filePart);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);
        applyAuthorization(headers, task.authorization());

        try {
            ResponseEntity<byte[]> response = restTemplate.exchange(
                    url,
                    HttpMethod.POST,
                    new HttpEntity<>(body, headers),
                    byte[].class
            );
            byte[] responseBody = response.getBody();
            if (responseBody == null || responseBody.length == 0) {
                throw new SeeThroughTaskException(502, "see_through 返回空文件");
            }

            HttpHeaders responseHeaders = response.getHeaders();
            String filename = parseFilename(responseHeaders.getFirst(HttpHeaders.CONTENT_DISPOSITION), task.filename());
            String contentType = responseHeaders.getContentType() == null
                    ? MediaType.APPLICATION_OCTET_STREAM_VALUE
                    : responseHeaders.getContentType().toString();

            return new SeeThroughResult(
                    filename,
                    contentType,
                    responseHeaders.getFirst("X-Cleanup-Token"),
                    responseBody,
                    responseHeaders.getOrDefault(HttpHeaders.SET_COOKIE, List.of())
            );
        } catch (HttpStatusCodeException ex) {
            throw new SeeThroughTaskException(ex.getStatusCode().value(), ex.getResponseBodyAsString());
        } catch (RestClientException ex) {
            throw new SeeThroughTaskException(502, "调用 see_through 失败: " + ex.getMessage());
        }
    }

    public String cleanup(String token, String authorization) {
        String url = buildUrl("/api/see-through/cleanup");
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        applyAuthorization(headers, authorization);

        try {
            ResponseEntity<String> response = restTemplate.exchange(
                    url,
                    HttpMethod.POST,
                    new HttpEntity<>("{\"token\":\"" + escapeJson(token) + "\"}", headers),
                    String.class
            );
            return response.getBody() == null ? "{}" : response.getBody();
        } catch (HttpStatusCodeException ex) {
            throw new SeeThroughTaskException(ex.getStatusCode().value(), ex.getResponseBodyAsString());
        } catch (RestClientException ex) {
            throw new SeeThroughTaskException(502, "调用 see_through cleanup 失败: " + ex.getMessage());
        }
    }

    public String health() {
        String url = buildUrl("/api/see-through/health");
        try {
            ResponseEntity<String> response = restTemplate.getForEntity(url, String.class);
            return response.getBody() == null ? "{}" : response.getBody();
        } catch (HttpStatusCodeException ex) {
            throw new SeeThroughTaskException(ex.getStatusCode().value(), ex.getResponseBodyAsString());
        } catch (RestClientException ex) {
            throw new SeeThroughTaskException(502, "调用 see_through health 失败: " + ex.getMessage());
        }
    }

    public ResponseEntity<byte[]> getRaw(String path, String authorization) {
        String url = buildUrl(path);
        HttpHeaders headers = new HttpHeaders();
        applyAuthorization(headers, authorization);

        try {
            return restTemplate.exchange(
                    URI.create(url),
                    HttpMethod.GET,
                    new HttpEntity<>(headers),
                    byte[].class
            );
        } catch (HttpStatusCodeException ex) {
            throw new SeeThroughTaskException(ex.getStatusCode().value(), ex.getResponseBodyAsString());
        } catch (RestClientException ex) {
            throw new SeeThroughTaskException(502, "调用 see_through 失败: " + ex.getMessage());
        }
    }

    private String parseFilename(String contentDisposition, String originalFilename) {
        if (contentDisposition != null) {
            ContentDisposition disposition = ContentDisposition.parse(contentDisposition);
            if (disposition.getFilename() != null && !disposition.getFilename().isBlank()) {
                return disposition.getFilename();
            }
        }

        int dot = originalFilename.lastIndexOf('.');
        String stem = dot > 0 ? originalFilename.substring(0, dot) : originalFilename;
        return stem + ".psd";
    }

    private String buildUrl(String path) {
        return UriComponentsBuilder
                .fromHttpUrl(properties.getBaseUrl().replaceAll("/+$", ""))
                .path(path)
                .toUriString();
    }

    private void applyAuthorization(HttpHeaders headers, String authorization) {
        if (authorization != null && !authorization.isBlank()) {
            headers.set(HttpHeaders.AUTHORIZATION, authorization);
        } else if (properties.getAuthToken() != null && !properties.getAuthToken().isBlank()) {
            headers.setBearerAuth(properties.getAuthToken());
        }
    }

    private String escapeJson(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
