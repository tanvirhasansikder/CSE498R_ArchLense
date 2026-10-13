package com.example.service;

import com.example.model.User;
import com.example.repository.UserRepository;

public class UserService<T> {
    private final UserRepository repository;

    public UserService(UserRepository repository) {
        this.repository = repository;
    }

    public User getUser(long id, T context) {
        var result = repository.findById(id);
        return result.orElse(null);
    }
}
