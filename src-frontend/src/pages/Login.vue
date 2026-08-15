<template>
  <q-page class="login-page column flex items-center justify-center q-pt-xl">
    <div
      class="login-hero"
      :class="{ 'is-ready': heroReady }"
      aria-hidden="true"
    >
      <div class="login-hero__media">
        <img
          class="login-hero__img"
          :src="heroImage"
          alt=""
          width="1024"
          height="768"
        />
      </div>
      <div class="login-hero__overlay" />
    </div>

    <login-card :reset-token="resetToken" />

    <h4 v-if="$q.platform.is.electron" class="q-my-sm text-white">OR</h4>

    <login-rfid-card v-if="$q.platform.is.electron" />

    <a
      v-if="!$q.platform.is.capacitor"
      href="/admin/"
      class="admin-link q-mt-lg"
    >
      {{ $t('loginCard.djangoAdmin') }}
    </a>
  </q-page>
</template>

<script>
import LoginRfidCard from '@components/LoginRfidCard.vue';
import LoginCard from '@components/LoginCard.vue';
import { mapGetters } from 'vuex';
import heroImage from '../assets/img/login-hero.jpg';

export default {
  name: 'LoginPage',
  components: {
    LoginRfidCard,
    LoginCard,
  },
  props: {
    resetToken: {
      type: String,
      default: null,
    },
  },
  data() {
    return {
      heroImage,
      heroReady: false,
    };
  },
  mounted() {
    window.requestAnimationFrame(() => {
      this.heroReady = true;
    });
  },
  computed: {
    ...mapGetters('config', ['images']),
  },
};
</script>

<style scoped>
.header-image-mobile {
  max-height: 50px;
}

.login-hero,
.login-hero__media,
.login-hero__overlay {
  position: fixed;
  inset: 0;
}

.login-hero {
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
  background: #1a2248;
}

.login-hero__media {
  overflow: hidden;
}

.login-hero__img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  transform: scale(1.06);
  will-change: transform;
}

.login-hero.is-ready .login-hero__img {
  animation: login-kenburns 18s ease-out both;
}

.login-hero__overlay {
  background: linear-gradient(
      105deg,
      rgba(26, 34, 72, 0.88) 0%,
      rgba(38, 50, 106, 0.55) 48%,
      rgba(26, 34, 72, 0.25) 100%
    ),
    linear-gradient(
      180deg,
      rgba(26, 34, 72, 0.35) 0%,
      transparent 35%,
      rgba(26, 34, 72, 0.55) 100%
    );
}

.login-page > :not(.login-hero) {
  position: relative;
  z-index: 1;
}

.admin-link {
  font-size: 11px;
  opacity: 0.35;
  color: #fff;
  text-decoration: none;
}

.admin-link:hover {
  opacity: 0.7;
}

@media (max-width: 767px) {
  .login-hero__img {
    transform: none;
    animation: none !important;
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-hero__img,
  .login-hero.is-ready .login-hero__img {
    transform: none;
    animation: none;
  }
}

@keyframes login-kenburns {
  from {
    transform: scale(1.06);
  }
  to {
    transform: scale(1);
  }
}
</style>
