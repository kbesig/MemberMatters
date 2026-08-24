<template>
  <div>
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h6">{{ $t('billingGroup.manageGroups') }}</div>
      <q-btn
        color="primary"
        :icon="icons.add"
        :label="$t('billingGroup.createGroup')"
        @click="openCreateDialog"
      />
    </div>

    <q-table
      :rows="groups"
      :columns="columns"
      :no-data-label="$t('billingGroup.noGroups')"
      :loading="loading"
      row-key="id"
      :filter="filter"
      class="full-width"
      @row-click="(evt, row) => openDetail(row)"
    >
      <template v-slot:top-right>
        <q-input
          v-model="filter"
          outlined
          dense
          debounce="300"
          placeholder="Search"
        >
          <template v-slot:append>
            <q-icon :name="icons.search" />
          </template>
        </q-input>
      </template>
    </q-table>

    <!-- Detail dialog -->
    <q-dialog v-model="showDetail" @hide="selectedGroup = null">
      <q-card style="min-width: 500px; max-width: 700px">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ selectedGroup?.name }}</div>
          <q-space />
          <q-btn icon="mdi-close" flat round dense v-close-popup />
        </q-card-section>

        <q-card-section>
          <div class="text-subtitle2 q-mb-sm">
            {{ $t('billingGroup.primaryMember') }}:
            {{ selectedGroup?.primaryMember?.name || '—' }}
          </div>

          <div class="text-subtitle2 q-mt-md q-mb-sm">
            {{ $t('billingGroup.members') }}
          </div>
          <q-list dense bordered>
            <q-item v-for="member in selectedGroup?.members" :key="member.id">
              <q-item-section>
                <q-item-label>{{ member.name }}</q-item-label>
                <q-item-label caption v-if="member.isPrimary">
                  {{ $t('billingGroup.isPrimary') }}
                </q-item-label>
              </q-item-section>
              <q-item-section side v-if="!member.isPrimary">
                <q-btn
                  flat
                  round
                  dense
                  size="sm"
                  color="negative"
                  icon="mdi-account-remove"
                  :title="$t('billingGroup.removeMember')"
                  @click="adminRemoveMember(member)"
                />
              </q-item-section>
            </q-item>
          </q-list>

          <!-- Add member -->
          <div class="q-mt-md">
            <div class="text-subtitle2 q-mb-sm">
              {{ $t('billingGroup.inviteMember') }}
            </div>
            <div class="row q-gutter-sm">
              <q-input
                v-model="addMemberEmail"
                :label="$t('billingGroup.inviteMemberEmail')"
                outlined
                dense
                class="col"
              />
              <q-btn
                color="primary"
                :label="$t('billingGroup.inviteMember')"
                :loading="loadingAdd"
                :disable="!addMemberEmail.trim()"
                @click="adminAddMember"
              />
            </div>
          </div>

          <!-- Invitations -->
          <template v-if="selectedGroupInvitations.length">
            <div class="text-subtitle2 q-mt-md q-mb-sm">
              {{ $t('billingGroup.pendingInvitations') }}
            </div>
            <q-list dense bordered>
              <q-item v-for="inv in selectedGroupInvitations" :key="inv.id">
                <q-item-section>
                  <q-item-label>{{ inv.email }}</q-item-label>
                  <q-item-label caption>
                    {{ $t('billingGroup.invitationExpires') }}:
                    {{ formatDate(inv.expiresDate) }}
                  </q-item-label>
                </q-item-section>
                <q-item-section side>
                  <div class="row q-gutter-xs">
                    <q-btn
                      flat
                      dense
                      size="sm"
                      :label="$t('billingGroup.resendInvitation')"
                      @click="adminResendInvitation(inv.id)"
                    />
                    <q-btn
                      flat
                      dense
                      size="sm"
                      color="negative"
                      :label="$t('billingGroup.cancelInvitation')"
                      @click="adminCancelInvitation(inv.id)"
                    />
                  </div>
                </q-item-section>
              </q-item>
            </q-list>
          </template>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn
            flat
            color="negative"
            :label="$t('billingGroup.deleteGroup')"
            :loading="loadingDelete"
            @click="adminDeleteGroup"
          />
          <q-btn flat v-close-popup :label="$t('button.close')" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Create dialog -->
    <q-dialog v-model="showCreate">
      <q-card style="min-width: 350px">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ $t('billingGroup.createGroup') }}</div>
          <q-space />
          <q-btn icon="mdi-close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="newGroupName"
            :label="$t('billingGroup.groupName')"
            outlined
          />
          <q-input
            v-model="newGroupPrimaryEmail"
            label="Primary Member Email"
            outlined
            class="q-mt-sm"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('button.cancel')" v-close-popup />
          <q-btn
            color="primary"
            :label="$t('billingGroup.createGroup')"
            :loading="loadingCreate"
            :disable="!newGroupName.trim()"
            @click="adminCreateGroup"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script lang="ts">
import icons from '@icons';

export default {
  name: 'AdminBillingGroupManager',
  data() {
    return {
      loading: true,
      filter: '',
      groups: [] as {
        id: number;
        name: string;
        primaryMember: { id: number; name: string } | null;
        memberCount: number;
        members: { id: number; name: string; isPrimary: boolean }[];
      }[],
      showDetail: false,
      selectedGroup: null as null | (typeof this.groups)[0],
      selectedGroupInvitations: [] as {
        id: number;
        email: string;
        expiresDate: string;
      }[],
      addMemberEmail: '',
      loadingAdd: false,
      loadingDelete: false,
      showCreate: false,
      newGroupName: '',
      newGroupPrimaryEmail: '',
      loadingCreate: false,
    };
  },
  computed: {
    icons() {
      return icons;
    },
    columns() {
      return [
        {
          name: 'name',
          label: this.$t('billingGroup.groupName'),
          field: 'name',
          sortable: true,
          align: 'left',
        },
        {
          name: 'primaryMember',
          label: this.$t('billingGroup.primaryMember'),
          field: (row: (typeof this.groups)[0]) =>
            row.primaryMember?.name || '—',
          sortable: true,
          align: 'left',
        },
        {
          name: 'memberCount',
          label: this.$t('billingGroup.memberCount'),
          field: 'memberCount',
          sortable: true,
          align: 'left',
        },
      ];
    },
  },
  async mounted() {
    await this.fetchGroups();
  },
  methods: {
    formatDate(dateStr: string) {
      return new Date(dateStr).toLocaleDateString('en-au');
    },
    async fetchGroups() {
      this.loading = true;
      try {
        const result = await this.$axios.get('/api/admin/billing-groups/');
        this.groups = Array.isArray(result.data) ? result.data : [];
      } catch {
        this.groups = [];
      } finally {
        this.loading = false;
      }
    },
    async openDetail(group: (typeof this.groups)[0]) {
      try {
        const result = await this.$axios.get(
          `/api/admin/billing-groups/${group.id}/`
        );
        if (result.data) {
          this.selectedGroup = result.data;
        }
      } catch {
        this.selectedGroup = group;
      }
      // Fetch invitations via admin endpoint
      try {
        const invResult = await this.$axios.post(
          `/api/admin/billing-groups/${group.id}/invites/`,
          { action: 'list' }
        );
        this.selectedGroupInvitations = Array.isArray(invResult.data)
          ? invResult.data
          : [];
      } catch {
        this.selectedGroupInvitations = [];
      }
      this.showDetail = true;
    },
    openCreateDialog() {
      this.newGroupName = '';
      this.newGroupPrimaryEmail = '';
      this.showCreate = true;
    },
    async adminCreateGroup() {
      if (!this.newGroupName.trim()) return;
      this.loadingCreate = true;
      try {
        const payload: { name: string; primary_member_email?: string } = {
          name: this.newGroupName.trim(),
        };
        if (this.newGroupPrimaryEmail.trim()) {
          payload.primary_member_email = this.newGroupPrimaryEmail.trim();
        }
        const result = await this.$axios.post(
          '/api/admin/billing-groups/',
          payload
        );
        if (result.data) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billingGroup.createGroupSuccess'),
          });
          this.showCreate = false;
          await this.fetchGroups();
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.createGroupFailed'),
        });
      } finally {
        this.loadingCreate = false;
      }
    },
    async adminDeleteGroup() {
      if (!this.selectedGroup) return;
      this.$q
        .dialog({
          title: this.$t('billingGroup.deleteGroup'),
          message: this.$t('billingGroup.deleteGroupConfirm'),
          cancel: this.$t('button.cancel'),
          persistent: true,
        })
        .onOk(async () => {
          this.loadingDelete = true;
          try {
            await this.$axios.delete(
              `/api/admin/billing-groups/${this.selectedGroup!.id}/`
            );
            this.$q.notify({
              type: 'positive',
              message: this.$t('billingGroup.deleteGroupSuccess'),
            });
            this.showDetail = false;
            await this.fetchGroups();
          } catch {
            this.$q.notify({
              type: 'negative',
              message: this.$t('billingGroup.deleteGroupFailed'),
            });
          } finally {
            this.loadingDelete = false;
          }
        });
    },
    async adminAddMember() {
      if (!this.selectedGroup || !this.addMemberEmail.trim()) return;
      this.loadingAdd = true;
      try {
        const result = await this.$axios.post(
          `/api/admin/billing-groups/${this.selectedGroup.id}/members/`,
          { action: 'add', email: this.addMemberEmail.trim() }
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billingGroup.inviteMemberSent'),
          });
          this.addMemberEmail = '';
          await this.openDetail(this.selectedGroup);
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('billingGroup.inviteMemberFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.inviteMemberFailed'),
        });
      } finally {
        this.loadingAdd = false;
      }
    },
    async adminRemoveMember(member: { id: number; name: string }) {
      if (!this.selectedGroup) return;
      this.$q
        .dialog({
          title: this.$t('billingGroup.removeMember'),
          message: this.$t('billingGroup.removeMemberConfirm', {
            name: member.name,
          }),
          cancel: this.$t('button.cancel'),
          persistent: true,
        })
        .onOk(async () => {
          try {
            const result = await this.$axios.post(
              `/api/admin/billing-groups/${this.selectedGroup!.id}/members/`,
              { action: 'remove', member_id: member.id }
            );
            if (result.data.success) {
              this.$q.notify({
                type: 'positive',
                message: this.$t('billingGroup.removeMemberSuccess'),
              });
              await this.openDetail(this.selectedGroup!);
            } else {
              this.$q.notify({
                type: 'negative',
                message: this.$t('billingGroup.removeMemberFailed'),
              });
            }
          } catch {
            this.$q.notify({
              type: 'negative',
              message: this.$t('billingGroup.removeMemberFailed'),
            });
          }
        });
    },
    async adminResendInvitation(id: number) {
      if (!this.selectedGroup) return;
      try {
        await this.$axios.post(
          `/api/admin/billing-groups/${this.selectedGroup.id}/invites/`,
          { action: 'resend', invite_id: id }
        );
        this.$q.notify({
          type: 'positive',
          message: this.$t('billingGroup.resendSuccess'),
        });
        await this.openDetail(this.selectedGroup);
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.resendFailed'),
        });
      }
    },
    async adminCancelInvitation(id: number) {
      if (!this.selectedGroup) return;
      try {
        await this.$axios.post(
          `/api/admin/billing-groups/${this.selectedGroup.id}/invites/`,
          { action: 'cancel', invite_id: id }
        );
        this.$q.notify({
          type: 'positive',
          message: this.$t('billingGroup.cancelInvitationSuccess'),
        });
        await this.openDetail(this.selectedGroup);
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.cancelInvitationFailed'),
        });
      }
    },
  },
};
</script>
